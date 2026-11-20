"""Key poses -> data for kimodo_keyposes.py: world rotation of every bone "posed" vs "the same frame after retarget"
(posed = output of prop_in_hands --frames on that sample), Kimodo axes -> character (C) and axis control positions.
blender -b --python pipeline/motion/keyposes_to_kimodo.py -- poses.glb merged.glb sample.bvh out.json 0,44 [action=attack] [--skeleton X]
Import order matters: the first GLB = poses, the second = retarget of the same sample (actions `<action>*`).
Rotations are keyed by SOMA bone (kimodo_keyposes.py reads them), and "hips" = where the source's hips must be for the
retarget to put the rig's hips where the pose has them (keypose_root.py); the rig bones come from its skeleton profile."""
import bpy, sys, os, json
import numpy as np
from mathutils import Matrix
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import skeleton
import keypose_root

a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
a, SKEL = skeleton.take_arg(a)
if len(a) < 5 or a[0] in ("-h", "--help"):
    print(__doc__); raise SystemExit(0 if a[:1] in (["-h"], ["--help"]) else 2)
poses, raw, bvh, out, frames = a[0], a[1], a[2], a[3], [int(x) for x in a[4].split(",")]
ACTION = a[5] if len(a) > 5 else "attack"
bpy.ops.wm.read_factory_settings(use_empty=True)


def load(glb):
    before = set(bpy.data.objects); bpy.ops.import_scene.gltf(filepath=glb)
    arm = next(o for o in set(bpy.data.objects) - before if o.type == "ARMATURE")
    arm.animation_data.action = next(x for x in bpy.data.actions if x.name.startswith(ACTION) and x not in USED); USED.append(arm.animation_data.action)
    return arm


USED = []
A1 = load(poses); A0 = load(raw)
bpy.ops.import_anim.bvh(filepath=bvh, rotate_mode="QUATERNION", axis_forward="-Z", axis_up="Y", update_scene_fps=False)
src = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o not in (A0, A1))
SRC = skeleton.load("soma")
TGT = skeleton.for_rig(SKEL, {b.name: b.parent.name if b.parent else None for b in A1.data.bones}).prof
MAP = dict(SRC.pairs(TGT))   # SOMA bone -> rig bone (full names)
def whead(ob, n, rest=True):
    m = ob.data.bones[n].matrix_local if rest else ob.pose.bones[n].matrix
    return ob.matrix_world @ m.translation


def basis(ob, S):
    x = (whead(ob, S.bone("upper_arm", "L")) - whead(ob, S.bone("upper_arm", "R"))).normalized()
    z = whead(ob, S.bone("neck")) - whead(ob, S.bone("hips")); z = (z - x * z.dot(x)).normalized()
    return Matrix((x, z.cross(x), z)).transposed()


C = basis(A1, TGT) @ basis(src, SRC).inverted()
wrot = lambda ob, n: (ob.matrix_world @ ob.pose.bones[n].matrix).to_3x3().normalized()
SH, TH = SRC.bone("hips"), TGT.bone("hips")
lift = lambda ob, S: whead(ob, S.bone("hips")).z - min(whead(ob, n).z for n in S.bones("foot"))
K = lift(A1, TGT) / lift(src, SRC)   # the retarget's hip scale (soma_to_mixamo.py)
v3 = lambda v: np.array(v[:])
sc = bpy.context.scene; res = {"C": [list(r) for r in C], "D": {}, "hips": {}, "control": {}}
for f in frames:
    sc.frame_set(f); bpy.context.view_layer.update()
    res["D"][f] = {s: [list(r) for r in (wrot(A1, t) @ wrot(A0, t).inverted())] for s, t in MAP.items()}
    h = keypose_root.source(v3(whead(A1, TH, False)), v3(whead(src, SH)), v3(whead(A1, TH)), np.array(C), K)
    res["hips"][f] = [float(x) for x in h]
    print("pose fr. %d: rig hips %+.1f cm vs the sample (z %+.1f) -> source hips z %.1f" % (
        f, 100 * (whead(A1, TH, False) - whead(A0, TH, False)).length, 100 * (whead(A1, TH, False) - whead(A0, TH, False)).z, h[2]))
# axis check: source joint positions at Kimodo frame 55 (the BVH starts at frame f0)
f0 = int(src.animation_data.action.frame_range[0]); sc.frame_set(f0 + 55); bpy.context.view_layer.update()
res["control"] = {n: list(whead(src, n, False)) for n in (SRC.bone("hips"), SRC.bone("head"), SRC.bone("hand", "L"),
                                                            SRC.bone("hand", "R"), SRC.bone("foot", "L"))}
res["src_scale"] = src.matrix_world.to_scale()[0]; res["hip_scale"] = K
json.dump(res, open(out, "w"), indent=0)
print("POSES OK", out, "f0", f0)
