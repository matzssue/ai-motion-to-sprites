"""stages.py (helpers of character.py): stage freshness by file times, Kimodo key frames.
python -m pytest tests  (or: python tests/test_stages.py)"""
import os, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
from stages import fresh, keys

R = {"phases": [{"duration": 1.0}, {"duration": 1.2}, {"duration": 0.8}, {"duration": 1.2}]}   # 4.2 s -> last frame 125


def test_keys_loop_ends_in_first_pose():
    assert keys(R, [0, 44]) == "0:0,55:44,125:0"


def test_keys_one_shot_holds_last_pose():
    assert keys(R, [0, 44], loop=False) == "0:0,55:44,125:44"
    assert keys({"phases": [{"duration": 1.0}]}, [0, 24], loop=False) == "0:0,30:24"   # last pose already at the end


def test_fresh():
    d = tempfile.mkdtemp(); out, a, b = (os.path.join(d, n) for n in ("out", "a", "b"))
    for p in (out, a, b): open(p, "w").close()
    assert not fresh(os.path.join(d, "missing"), a)
    os.utime(a, (100, 100)); os.utime(b, (200, 200)); os.utime(out, (150, 150))
    assert fresh(out, a) and not fresh(out, a, b)
    assert fresh(out, a, os.path.join(d, "missing"))   # a missing input does not make the output stale


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
