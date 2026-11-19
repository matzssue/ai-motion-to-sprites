"""JSON configs checked against schemas/*.schema.json before any Blender step: a problem is reported with its file and
JSON path instead of a KeyError in the middle of a run. Host Python only: Blender's bundled Python may lack jsonschema,
so Blender scripts must not import this module."""
import json
import os

SCHEMAS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "schemas")


def schema(kind, require=()):
    """schemas/<kind>.schema.json; `require` adds top-level keys the caller indexes (an `ai` motion needs `phases`)."""
    s = json.load(open(os.path.join(SCHEMAS, kind + ".schema.json"), encoding="utf-8"))
    if require: s["required"] = sorted(set(s.get("required", [])) | set(require))
    return s


def json_path(parts):
    return "$" + "".join("[%d]" % p if isinstance(p, int) else ".%s" % p for p in parts)


def problems(data, kind, require=()):
    """List of "<JSON path>: <message>" (empty = valid)."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise SystemExit("jsonschema is not installed: pip install -e .  (or pip install jsonschema)")
    out = []
    for e in sorted(Draft202012Validator(schema(kind, require)).iter_errors(data), key=lambda e: json_path(e.absolute_path)):
        hint = e.schema.get("description") if e.validator in ("anyOf", "oneOf") and isinstance(e.schema, dict) else None
        out.append("%s: %s" % (json_path(e.absolute_path), hint or e.message))
    return out


def load(path, kind, require=()):
    """The JSON file, or SystemExit naming the file and the JSON path of every problem."""
    try:
        data = json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        raise SystemExit("%s: not valid JSON (%s)" % (path, e))
    p = problems(data, kind, require)
    if p: raise SystemExit("%s does not match schemas/%s.schema.json:\n  %s" % (path, kind, "\n  ".join(p)))
    return data


def load_character(path):
    """character.json plus the configs it points to: the rig config, each `ai` motion (needs `phases`) and each prop
    motion (needs `grip`). A file that does not exist yet is left to the stage that reads it."""
    C = load(path, "character"); base = os.path.dirname(os.path.abspath(path))

    def r(p): return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))
    need = {}
    for a in C["actions"].values():
        if "ai" in a: need.setdefault(r(a["ai"]), set()).add("phases")
        if a.get("prop") and (a.get("ai") or a.get("motion")): need.setdefault(r(a.get("ai") or a["motion"]), set()).add("grip")
    for p, kind, req in [(r(C["rig_config"]), "rig", ())] + [(p, "motion", tuple(k)) for p, k in need.items()]:
        if os.path.exists(p): load(p, kind, req)
    return C
