"""tools/check_licenses.py: SPDX expressions and classifier names against the commercial-use allowlist.
python -m pytest tests  (or: python tests/test_check_licenses.py)"""
import json, os, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from check_licenses import verdict, main

# what PyPI declared for the packages CI installed on Python 3.11
PASS = ["BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", "MIT-CMU", "PSF-2.0", "BSD-3-Clause", "MIT", "BSD License",
        "MIT License", "MIT License; BSD License", "(MIT OR Apache-2.0) AND BSD-3-Clause", "Apache-2.0 WITH LLVM-exception",
        "MIT OR GPL-2.0-only"]   # OR: one allowed side is enough, the licensee picks MIT


def test_permissive_pass():
    for s in PASS: assert verdict(s) == (True, []), s


def test_copyleft_noncommercial_and_unknown_fail():
    assert verdict("GPL-3.0-or-later") == (False, ["GPL-3.0-or-later"])
    assert verdict("GPL-3.0 AND MIT") == (False, ["GPL-3.0"])
    assert verdict("CC-BY-NC-4.0") == (False, ["CC-BY-NC-4.0"])
    assert verdict("GPL-2.0-only WITH Classpath-exception-2.0") == (False, ["GPL-2.0-only"])
    assert verdict("LGPL-3.0-only OR MPL-2.0") == (False, ["LGPL-3.0-only", "MPL-2.0"])
    assert verdict("MIT License; GNU General Public License v3 (GPLv3)") == (False, ["GNU General Public License v3 (GPLv3)"])
    for s in ("", "   ", None, "UNKNOWN"): assert verdict(s)[0] is False, s
    assert verdict("(MIT AND")[0] is False


def test_main_lists_every_offender():
    rep = [{"Name": "numpy", "Version": "2.4.6", "License": PASS[0]}, {"Name": "a", "Version": "1", "License": "GPL-3.0 AND MIT"},
           {"Name": "b", "Version": "2", "License": "UNKNOWN"}]
    f = os.path.join(tempfile.mkdtemp(), "r.json"); json.dump(rep, open(f, "w"))
    assert main(["x", f]) == 1
    json.dump(rep[:1], open(f, "w"))
    assert main(["x", f]) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
