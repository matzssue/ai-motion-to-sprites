"""What changed between two sets of poses: per bone the largest difference of its own rotation, in degrees, sorted.
Hand-posed key poses are read-only input: a step that writes them again (a fix, a re-export, a fist put on every key) shows
with this what it changed, before anyone calls the result approved.

blender -b --python pipeline/checks/pose_diff.py -- --a before.blend --b after.glb [--action attack] [--action-b attack]
    [--frames 0,14,20] [--threshold 1] [--strict] [--out diff.json]
A source is a GLB or a .blend (opened, never saved). `--action`: the action to read (default: the one on the armature, or
the file's only one); `--action-b` when the second file names it differently. `--frames`: default every whole frame of
the first source's action. Prints every bone over `--threshold` deg (default 1), most changed first, and the bones only
one source has; `--strict` exits 1 when any bone is over. Rotation is the bone's own (against its parent and its rest),
so a turned upper arm does not show up on the hand below it. Positions and scales are not compared."""
import json
import os
import sys

import numpy as np


def angle(p, q):
    """Degrees between two rotations given as unit quaternions (w, x, y, z)."""
    return float(np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(p, q)))))))


def diff(a, b, threshold=1.0):
    """`a`, `b`: {frame: {bone: quaternion}}. -> {"rows": [(bone, largest difference in deg, its frame)] most changed first,
    "over": the bones past `threshold`, "only_a" / "only_b": bones one source lacks, "frames": the frames both have}."""
    frames = sorted(set(a) & set(b)); bones_a = set().union(*(a[f] for f in frames)) if frames else set()
    bones_b = set().union(*(b[f] for f in frames)) if frames else set(); rows = []
    for n in sorted(bones_a & bones_b):
        d = [(angle(a[f][n], b[f][n]), f) for f in frames if n in a[f] and n in b[f]]
        if d: rows.append((n, *max(d)))
    rows.sort(key=lambda r: (-r[1], r[0]))
    return {"rows": rows, "over": [r[0] for r in rows if r[1] > threshold], "only_a": sorted(bones_a - bones_b),
            "only_b": sorted(bones_b - bones_a), "frames": frames}


def lines(d, threshold):
    """The printed report of `diff`."""
    out = ["POSE DIFF on frames %s: %d of %d bones over %g deg" % (
        ",".join(map(str, d["frames"])) if len(d["frames"]) <= 12 else "%s-%s (%d)" % (d["frames"][0], d["frames"][-1], len(d["frames"])),
        len(d["over"]), len(d["rows"]), threshold)]
    out += ["  CHANGED %-24s %6.1f deg (fr. %s)" % r for r in d["rows"] if r[1] > threshold]
    for k, name in (("only_a", "first"), ("only_b", "second")):
        if d[k]: out.append("  only in the %s source: %s" % (name, ", ".join(d[k])))
    return out


def main():
    import argparse

    import bpy

    ap = argparse.ArgumentParser(description="Per bone, the largest rotation difference between two pose sources.")
    ap.add_argument("--a", required=True); ap.add_argument("--b", required=True); ap.add_argument("--action", default=None)
    ap.add_argument("--action-b", default=None); ap.add_argument("--frames", default=None); ap.add_argument("--threshold", type=float, default=1.0)
    ap.add_argument("--strict", action="store_true"); ap.add_argument("--out", default=None)
    A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])

    def read(path, action, frames):
        """({frame: {bone: quaternion}}, the frames read) of one source."""
        if path.lower().endswith(".blend"): bpy.ops.wm.open_mainfile(filepath=os.path.abspath(path))
        else: bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
        arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
        if len(arms) != 1: raise SystemExit("%s: one armature expected, found %d" % (path, len(arms)))
        arm = arms[0]; cur = arm.animation_data.action if arm.animation_data else None
        act = bpy.data.actions.get(action) if action else cur or (bpy.data.actions[0] if len(bpy.data.actions) == 1 else None)
        if act is None: raise SystemExit("%s: %s (there are: %s)" % (path, "no action %s" % action if action else "name the action with --action",
                                                                     ", ".join(sorted(x.name for x in bpy.data.actions))))
        if arm.animation_data is None: arm.animation_data_create()
        arm.animation_data.action = act
        try: arm.animation_data.action_slot = act.slots[0]
        except (AttributeError, IndexError): pass
        f0, f1 = (int(round(x)) for x in act.frame_range); frames = frames or list(range(f0, f1 + 1)); out = {}
        for f in frames:
            bpy.context.scene.frame_set(f); bpy.context.view_layer.update()
            out[f] = {pb.name: tuple(pb.matrix_basis.to_quaternion()) for pb in arm.pose.bones}
        return out, frames

    frames = [int(x) for x in A.frames.split(",")] if A.frames else None
    a, frames = read(A.a, A.action, frames); b, _ = read(A.b, A.action_b or A.action, frames)
    d = diff(a, b, A.threshold)
    for line in lines(d, A.threshold): print(line)
    if A.out:
        json.dump({"a": A.a, "b": A.b, "threshold": A.threshold, "frames": d["frames"], "over": d["over"], "only_a": d["only_a"], "only_b": d["only_b"],
                   "bones": [{"bone": n, "deg": round(deg, 2), "frame": f} for n, deg, f in d["rows"]]}, open(A.out, "w", encoding="utf-8"), indent=1)
    print("POSE DIFF OK" if not d["over"] else "POSE DIFF CHANGED")
    if A.strict and d["over"]: sys.exit(1)


if __name__ == "__main__":
    main()
