"""Compare two versions of the same motion frame by frame: hands, elbows, prop, head, fingers.
Proof of "looks the same" after a tool change (reference = the approved version).
blender -b --python pipeline/checks/compare_motion.py -- --a reference.glb --b new.glb --action attack [--prop crossbow] [--out diff.json]
Output: lines `DIFF <part> max ... (fr. N)`, ending with `COMPARE IDENTICAL|DIFFERENT`. Identity limits: 0.5 mm and 0.5 deg."""
import bpy, sys, math, json, argparse
from mathutils import Matrix

ap = argparse.ArgumentParser(description="Compare two GLB versions of one action bone by bone.")
ap.add_argument("--a", required=True); ap.add_argument("--b", required=True); ap.add_argument("--action", required=True)
ap.add_argument("--prop", default=None); ap.add_argument("--out", default=None)
ap.add_argument("--limit-mm", type=float, default=0.5); ap.add_argument("--limit-deg", type=float, default=0.5)
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
BONES = ["Hips", "Spine2", "Neck", "Head", "LeftArm", "RightArm", "LeftForeArm", "RightForeArm", "LeftHand", "RightHand"]
FINGER_PREFIX = "finger_"


def trace(glb):
    """{frame: {bone: (world position, world rotation)}} + local rotations of fingers."""
    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=glb)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE"); arm.animation_data.action = bpy.data.actions[A.action]
    for pb in arm.pose.bones: pb.matrix_basis = Matrix()   # bones without curves: rest, not a pose from another action
    P = next((b.name.split(":")[0] + ":" for b in arm.data.bones if ":" in b.name), "")
    names = {n: P + n for n in BONES}
    if A.prop and A.prop in arm.pose.bones: names["prop"] = A.prop
    fingers = [b.name for b in arm.pose.bones if b.name.startswith(FINGER_PREFIX)]
    f0, f1 = (int(v) for v in arm.animation_data.action.frame_range); out = {}
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f); AW = arm.matrix_world; d = {}
        for k, n in names.items():
            M = AW @ arm.pose.bones[n].matrix; d[k] = (M.translation.copy(), M.to_3x3().normalized().to_quaternion())
        for n in fingers: d[n] = (None, arm.pose.bones[n].matrix_basis.to_quaternion())
        out[f] = d
    return out


def ang(a, b):
    x = math.degrees(a.rotation_difference(b).angle); return min(x, 360 - x)


SA, SB = trace(A.a), trace(A.b)
# a missing bone or frame is a difference: a renamed bone (e.g. other finger names) must not pass as IDENTICAL
missing = set(SA) != set(SB)
if missing: print("DIFF frames: %d vs %d" % (len(SA), len(SB)))
frames = sorted(set(SA) & set(SB)); res = {}
for k in SA[frames[0]]:
    if k not in SB[frames[0]]: print("DIFF bone missing in b:", k); missing = True; continue
    group = "fingers" if k.startswith(FINGER_PREFIX) else k
    for f in frames:
        pa, qa = SA[f][k]; pb_, qb = SB[f][k]
        w = res.setdefault(group, {"mm": 0.0, "mm_fr": None, "deg": 0.0, "deg_fr": None, "mm_sum": 0.0, "deg_sum": 0.0, "n": 0})
        dg = ang(qa, qb); mm = (pa - pb_).length * 1000 if pa is not None else 0.0
        w["mm_sum"] += mm; w["deg_sum"] += dg; w["n"] += 1
        if mm > w["mm"]: w["mm"], w["mm_fr"] = mm, f
        if dg > w["deg"]: w["deg"], w["deg_fr"] = dg, f
for k in SB[frames[0]]:
    if k not in SA[frames[0]]: print("DIFF bone missing in a:", k); missing = True
different = missing
for k, w in res.items():
    bad = w["mm"] > A.limit_mm or w["deg"] > A.limit_deg; different |= bad
    print("DIFF %-13s position max %6.1f mm (fr. %s, mean %5.1f) | rotation max %5.1f deg (fr. %s, mean %4.1f)%s" % (
        k, w["mm"], w["mm_fr"], w["mm_sum"] / w["n"], w["deg"], w["deg_fr"], w["deg_sum"] / w["n"], "  <-- different" if bad else ""))
if A.out: json.dump(res, open(A.out, "w", encoding="utf-8"), indent=1)
print("COMPARE", "DIFFERENT" if different else "IDENTICAL", "(%d frames)" % len(frames))
