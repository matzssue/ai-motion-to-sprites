"""Key poses -> data for kimodo_keyposes.py: world rotation of every bone "posed" vs "the same frame after retarget"
(posed = output of prop_in_hands --frames on that sample), Kimodo axes -> character (C) and axis control positions.
blender -b --python pipeline/motion/keyposes_to_kimodo.py -- poses.glb merged.glb sample.bvh out.json 0,44 [action=attack]
Import order matters: the first GLB = poses, the second = retarget of the same sample (actions `<action>*`)."""
import bpy, sys, json
from mathutils import Matrix

a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if len(a) < 5 or a[0] in ("-h", "--help"):
    print(__doc__); raise SystemExit(0 if a[:1] in (["-h"], ["--help"]) else 2)
poses, raw, bvh, out, frames = a[0], a[1], a[2], a[3], [int(x) for x in a[4].split(",")]
ACTION = a[5] if len(a) > 5 else "attack"
MAP = {"Hips": "Hips", "Spine1": "Spine", "Spine2": "Spine1", "Chest": "Spine2", "Neck1": "Neck", "Head": "Head"}
for s in ("Left", "Right"):
    MAP.update({s + "Shoulder": s + "Shoulder", s + "Arm": s + "Arm", s + "ForeArm": s + "ForeArm", s + "Hand": s + "Hand",
                s + "Leg": s + "UpLeg", s + "Shin": s + "Leg", s + "Foot": s + "Foot", s + "ToeBase": s + "ToeBase"})
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
P = "mixamorig:"


def whead(ob, n, rest=True):
    m = ob.data.bones[n].matrix_local if rest else ob.pose.bones[n].matrix
    return ob.matrix_world @ m.translation


def basis(ob, l, r, lo, hi, pre=""):
    x = (whead(ob, pre + l) - whead(ob, pre + r)).normalized()
    z = whead(ob, pre + hi) - whead(ob, pre + lo); z = (z - x * z.dot(x)).normalized()
    return Matrix((x, z.cross(x), z)).transposed()


C = basis(A1, "LeftArm", "RightArm", "Hips", "Neck", P) @ basis(src, "LeftArm", "RightArm", "Hips", "Neck1").inverted()
wrot = lambda ob, n: (ob.matrix_world @ ob.pose.bones[n].matrix).to_3x3().normalized()
sc = bpy.context.scene; res = {"C": [list(r) for r in C], "D": {}, "control": {}}
for f in frames:
    sc.frame_set(f); bpy.context.view_layer.update()
    res["D"][f] = {s: [list(r) for r in (wrot(A1, P + t) @ wrot(A0, P + t).inverted())] for s, t in MAP.items()}
# axis check: source joint positions at Kimodo frame 55 (the BVH starts at frame f0)
f0 = int(src.animation_data.action.frame_range[0]); sc.frame_set(f0 + 55); bpy.context.view_layer.update()
res["control"] = {n: list(whead(src, n, False)) for n in ("Hips", "Head", "LeftHand", "RightHand", "LeftFoot")}
res["src_scale"] = src.matrix_world.to_scale()[0]
json.dump(res, open(out, "w"), indent=0)
print("POSES OK", out, "f0", f0)
