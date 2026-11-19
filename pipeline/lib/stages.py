"""Pure helpers of character.py (no argparse, no Blender), importable by tests."""
import os


def fresh(out, *inputs):
    if not os.path.exists(out): return False
    return all(os.path.getmtime(out) >= os.path.getmtime(w) for w in inputs if os.path.exists(w))


def keys(R, fr, loop=True):
    """Kimodo frame (30 fps) : pose frame (24 fps); the last key = the first pose so the clip loops.
    A one-shot action ("loop": false, e.g. picking up loot) holds the last pose at the end."""
    last = int(round(sum(f["duration"] for f in R["phases"]) * 30)) - 1
    ks = ["%d:%d" % (int(round(f * 30 / 24)), f) for f in fr]
    if loop: ks.append("%d:%d" % (last, fr[0]))
    elif int(round(fr[-1] * 30 / 24)) < last: ks.append("%d:%d" % (last, fr[-1]))
    return ",".join(ks)
