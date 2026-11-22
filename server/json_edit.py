"""Edits one member of a JSON file in place, leaving every other byte as it was (key order, `_` comment keys,
indentation, one-line objects, line endings). The result is parsed back and compared with the intended data."""
import copy
import json
import re
from dataclasses import dataclass, field

_LITERAL = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null")


@dataclass
class Span:
    start: int
    end: int
    members: dict[str, tuple[int, "Span"]] = field(default_factory=dict)   # object: key -> (key start, value)
    is_object: bool = False


class _Scanner:
    def __init__(self, text: str):
        self.t = text; self.i = 0

    def ws(self):
        while self.i < len(self.t) and self.t[self.i] in " \t\r\n": self.i += 1

    def string(self) -> str:
        start = self.i; self.i += 1
        while self.t[self.i] != '"': self.i += 2 if self.t[self.i] == "\\" else 1
        self.i += 1
        return json.loads(self.t[start:self.i])

    def value(self) -> Span:
        self.ws(); start = self.i; c = self.t[self.i]
        if c == "{":
            node = Span(start, 0, is_object=True); self.i += 1; self.ws()
            if self.t[self.i] == "}": self.i += 1; node.end = self.i; return node
            while True:
                self.ws(); key_start = self.i; key = self.string(); self.ws()
                assert self.t[self.i] == ":"; self.i += 1
                node.members[key] = (key_start, self.value()); self.ws()
                if self.t[self.i] == ",": self.i += 1; continue
                assert self.t[self.i] == "}"; self.i += 1; node.end = self.i; return node
        if c == "[":
            self.i += 1; self.ws()
            if self.t[self.i] == "]": self.i += 1; return Span(start, self.i)
            while True:
                self.value(); self.ws()
                if self.t[self.i] == ",": self.i += 1; continue
                assert self.t[self.i] == "]"; self.i += 1; return Span(start, self.i)
        if c == '"': self.string(); return Span(start, self.i)
        m = _LITERAL.match(self.t, self.i)
        if not m: raise ValueError("unexpected character at %d" % self.i)
        self.i = m.end(); return Span(start, self.i)


def spans(text: str) -> Span:
    json.loads(text)   # a real JSON error message first; the scanner below assumes valid JSON
    return _Scanner(text).value()


def indent_unit(text: str) -> str:
    """The smallest indentation step of the file (a tab, or n spaces); one space for a file on one line."""
    widths = [len(m.group(1)) for m in re.finditer(r"\n( +)\S", text)]
    if re.search(r"\n\t+\S", text): return "\t"
    return " " * (min(widths) if widths else 1)


def _line_indent(text: str, pos: int) -> str:
    line_start = text.rfind("\n", 0, pos) + 1
    return re.match(r"[ \t]*", text[line_start:]).group(0)


def _render(value, multiline: bool, unit: str, indent: str, newline: str) -> str:
    if not multiline: return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, indent=unit).replace("\n", newline + indent)


def set_member(text: str, path: list[str], key: str, value) -> str:
    """`text` with object `path` (keys from the root) holding `key: value`: the old value's text is replaced, or the
    member is appended after the object's last member in the object's own style. Raises if the result differs from
    the intended data in any other place."""
    root = spans(text); node = root
    for p in path:
        if not node.is_object or p not in node.members: raise KeyError("no %s in the file" % ".".join(path))
        node = node.members[p][1]
    if not node.is_object: raise ValueError("%s is not an object" % ".".join(path))
    newline = "\r\n" if "\r\n" in text else "\n"; unit = indent_unit(text)
    multiline = "\n" in text[node.start:node.end]
    if key in node.members:
        key_start, old = node.members[key]
        indent = _line_indent(text, key_start)
        new = text[:old.start] + _render(value, "\n" in text[old.start:old.end] or multiline, unit, indent, newline) + text[old.end:]
    elif node.members:
        last_key_start, last = list(node.members.values())[-1]
        if multiline:
            indent = _line_indent(text, last_key_start)
            member = ",%s%s%s: %s" % (newline, indent, json.dumps(key, ensure_ascii=False), _render(value, True, unit, indent, newline))
        else:
            member = ", %s: %s" % (json.dumps(key, ensure_ascii=False), _render(value, False, unit, "", newline))
        new = text[:last.end] + member + text[last.end:]
    else:
        new = text[:node.start] + "{%s: %s}" % (json.dumps(key, ensure_ascii=False), _render(value, False, unit, "", newline)) + text[node.end:]
    want = copy.deepcopy(json.loads(text)); target = want
    for p in path: target = target[p]
    target[key] = value
    if json.loads(new) != want: raise AssertionError("internal error: the edited file does not hold the intended data")
    return new
