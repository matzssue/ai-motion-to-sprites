"""License gate for the installed runtime dependencies (stdlib only).
pip-licenses --from=mixed --format=json | python tools/check_licenses.py   (or: python tools/check_licenses.py report.json)
Every SPDX identifier of every package must be on ALLOWED; prints the accepted table, lists every offender, exits 1 on any."""
import json
import re
import sys

# permissive licenses that allow commercial use; nothing copyleft (GPL, LGPL, AGPL, MPL) and nothing non-commercial
ALLOWED = {
    "MIT", "MIT License", "MIT-CMU", "HPND", "BSD License", "BSD-2-Clause", "BSD-3-Clause", "BSD-3-Clause-Attribution", "0BSD",
    "Apache-2.0", "Apache Software License", "ISC", "PSF-2.0", "Python-2.0", "Python Software Foundation License", "Zlib",
    "CC0-1.0", "BSL-1.0", "Unlicense",
}
OPERATOR = re.compile(r"\s(?:AND|OR|WITH)\s")


def tokens(expr):
    return re.findall(r"\(|\)|[^\s()]+", expr)


def parse(expr):
    """SPDX expression -> nested ("AND"|"OR", [...]) / identifier string. `X WITH exception` is one unit judged by X:
    an exception only adds permissions. A string without AND/OR/WITH is one identifier (classifier names contain spaces
    and parentheses: "GNU General Public License v3 (GPLv3)")."""
    if not OPERATOR.search(expr): return expr.strip()
    ts = tokens(expr); pos = [0]

    def peek(): return ts[pos[0]] if pos[0] < len(ts) else None

    def take():
        pos[0] += 1; return ts[pos[0] - 1]

    def factor():
        if peek() == "(":
            take(); e = either()
            if take() != ")": raise ValueError("unbalanced parentheses in %r" % expr)
            return e
        t = take()
        if t is None or t in ("AND", "OR", "WITH", ")"): raise ValueError("bad license expression %r" % expr)
        if peek() == "WITH": take(); take()
        return t

    def both():
        parts = [factor()]
        while peek() == "AND": take(); parts.append(factor())
        return parts[0] if len(parts) == 1 else ("AND", parts)

    def either():
        parts = [both()]
        while peek() == "OR": take(); parts.append(both())
        return parts[0] if len(parts) == 1 else ("OR", parts)
    e = either()
    if peek() is not None: raise ValueError("bad license expression %r" % expr)
    return e


def judge(node):
    """-> (allowed, offending identifiers). AND: every part allowed. OR: one allowed side is enough, because the
    licensee may pick it (`MIT OR GPL-2.0-only` is used under MIT)."""
    if isinstance(node, str): return (node in ALLOWED, [] if node in ALLOWED else [node])
    op, parts = node; res = [judge(p) for p in parts]
    ok = all(r[0] for r in res) if op == "AND" else any(r[0] for r in res)
    return ok, [] if ok else [b for r in res for b in r[1]]


def verdict(license_str):
    """pip-licenses license string -> (allowed, offending identifiers). Several classifiers joined by ";" must all pass;
    an empty or UNKNOWN license fails."""
    parts = [p.strip() for p in (license_str or "").split(";") if p.strip()]
    if not parts or any(p.upper() == "UNKNOWN" for p in parts): return False, [license_str.strip() if license_str and license_str.strip() else "UNKNOWN"]
    bad = []
    for p in parts:
        try: ok, b = judge(parse(p))
        except ValueError as e: ok, b = False, [str(e)]
        if not ok: bad += b
    return not bad, bad


def main(argv):
    report = json.load(open(argv[1], encoding="utf-8")) if len(argv) > 1 else json.load(sys.stdin)
    bad = []
    for p in sorted(report, key=lambda p: p["Name"].lower()):
        ok, off = verdict(p.get("License", ""))
        print("%-4s %-28s %-10s %s" % ("ok" if ok else "FAIL", p["Name"], p.get("Version", ""), p.get("License", "")))
        if not ok: bad.append("%s %s: %s" % (p["Name"], p.get("Version", ""), ", ".join(off)))
    if bad:
        print("\nLICENSE GATE FAILED - not on the allowlist (tools/check_licenses.py):\n  " + "\n  ".join(bad)); return 1
    print("\nLICENSES OK (%d packages)" % len(report)); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
