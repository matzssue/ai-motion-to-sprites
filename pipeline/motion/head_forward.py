"""Head on the direction the character faces: per frame the neck and the head are turned so the head looks where the rest
pose faces, a little down and without roll; half of the turn goes to the neck. The motion model looks where its body
turns: the knight's attack looked up to 43 deg to the side through the whole clip (26 on average), which reads as a
character not watching its target in 8 fixed directions.
Motion file `head` (an action without it is not touched; chain.py runs this after the retarget and pose_upper_body.py):
    "mode": "lock"   straight ahead on every frame (an attack)
    "mode": "keep"   the clip's own head motion since its first frame, times `keep` (0-1, default 1), on top of straight
                     ahead (an idle that glances around); the first frame faces forward in both modes, so clips join
    "pitch_deg": 3   how far down it looks; "chest_max_deg": 70   the head never turns further than this from the chest
blender -b --python pipeline/motion/head_forward.py -- --clip clip.glb --motion motion.json --out clip.glb
    [--clip-action ai_source] [--skeleton X]
Prints the head's yaw and pitch before and after and the frames where the chest limit held it back."""
import argparse, json, math, os, sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import pose_track as PT
from audit_metrics import facing, head_angles
from collisions import rig_of

ap = argparse.ArgumentParser(description="Turn the head (and the neck) to the direction the character faces.")
ap.add_argument("--clip", required=True); ap.add_argument("--clip-action", default="ai_source")
ap.add_argument("--motion", required=True); ap.add_argument("--out", required=True); ap.add_argument("--skeleton", default=None)
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
H = json.load(open(A.motion, encoding="utf-8")).get("head") or {}
MODE = H.get("mode", "lock"); PITCH = float(H.get("pitch_deg", 3.0)); KEEP = float(H.get("keep", 1.0)); CAP = float(H.get("chest_max_deg", 70.0))

bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.clip)); sc = bpy.context.scene
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE"); acts = sorted(bpy.data.actions, key=lambda a: a.name)
act = next((a for a in acts if a.name == A.clip_action), None) or next((a for a in acts if a.name.startswith(A.clip_action)), None)
if act is None: raise SystemExit("%s: no action %s (there are: %s)" % (A.clip, A.clip_action, ", ".join(a.name for a in acts)))
arm.animation_data.action = act
try: arm.animation_data.action_slot = act.slots[0]
except (AttributeError, IndexError): pass
for _pb in arm.pose.bones: _pb.matrix_basis = Matrix()   # bones without curves here keep another action's pose
PROF = rig_of(arm, A.skeleton).prof; pb = arm.pose.bones; db = arm.data.bones
HEAD, NECK, CHEST = PROF.bone("head"), PROF.bone("neck"), PROF.spine[-1]
MW = arm.matrix_world; MW3 = MW.to_3x3().normalized(); W2A = MW3.inverted()
FACING = facing(*(np.array(MW @ db[PROF.bone("upper_arm", s)].head_local) for s in ("Left", "Right")))
def upd(): bpy.context.view_layer.update()


def rest_axis(name, world):
    """The bone's own axis that points along `world` in the rest pose."""
    return ((MW3 @ db[name].matrix_local.to_3x3().normalized()).inverted() @ Vector(world)).normalized()


HF, HU, CF = rest_axis(HEAD, FACING), rest_axis(HEAD, (0, 0, 1)), rest_axis(CHEST, FACING)
def world(n): upd(); return MW3 @ pb[n].matrix.to_3x3().normalized()
def frame(f, u): f = f.normalized(); u = (u - f * f.dot(u)).normalized(); return Matrix((f, u, f.cross(u))).transposed()


def turn(n, rot):
    upd(); M = pb[n].matrix.copy(); hd = M.translation.copy()
    pb[n].matrix = Matrix.Translation(hd) @ (W2A @ rot @ MW3).to_4x4() @ Matrix.Translation(-hd) @ M


f0, f1 = act.frame_range[0], act.frame_range[1]; TIMES = PT.key_times(f0, f1); poses, before, after, held = [], [], [], []
for t in TIMES:   # the targets first, from the clip as it is
    sc.frame_set(int(t), subframe=t - int(t)); upd()
    y, p = head_angles(world(HEAD) @ HF, FACING); before.append((y, p))
    cy = head_angles(world(CHEST) @ CF, FACING)[0]
    ty, tp, capped = PT.head_target(MODE, y, p, before[0][0], before[0][1], cy, PITCH, KEEP, CAP)
    if capped: held.append(round(t - f0, 1))
    tf, tu = PT.direction(ty, tp, FACING); want = frame(Vector(tf), Vector(tu)) @ frame(HF, HU).inverted()   # the head's world rotation
    turn(NECK, Quaternion().slerp((want @ world(HEAD).inverted()).to_quaternion(), 0.5).to_matrix())           # half on the neck
    turn(HEAD, want @ world(HEAD).inverted()); upd()
    poses.append({n: pb[n].matrix_basis.to_quaternion() for n in (NECK, HEAD)})
    after.append(head_angles(world(HEAD) @ HF, FACING) + (head_angles(world(HEAD) @ HF, FACING)[0] - cy,))
bags = [act] if hasattr(act, "fcurves") else [bg for la in act.layers for st in la.strips for bg in st.channelbags]
for bag in bags:
    for fc in [c for c in bag.fcurves if c.data_path.split('"')[1:2] in ([NECK], [HEAD]) and ".rotation" in c.data_path]: bag.fcurves.remove(fc)
prev = {}
for t, q in zip(TIMES, poses):
    for n in (NECK, HEAD):
        pb[n].rotation_mode = "QUATERNION"; v = q[n] if n not in prev or q[n].dot(prev[n]) >= 0 else -q[n]
        pb[n].rotation_quaternion = v; prev[n] = v; pb[n].keyframe_insert("rotation_quaternion", frame=t)
rng = lambda v: "%.0f..%.0f" % (min(v), max(v))   # noqa: E731
print("HEAD %s: yaw %s -> %s, pitch %s -> %s deg; against the chest up to %.0f deg; held back by the chest limit on %s" % (
    MODE, rng([b[0] for b in before]), rng([a[0] for a in after]), rng([b[1] for b in before]), rng([a[1] for a in after]),
    max(abs(a[2]) for a in after), held or "no frame"))
bpy.ops.export_scene.gltf(filepath=os.path.abspath(A.out), export_format="GLB", export_animations=True, export_force_sampling=False,
                          export_apply=False, export_materials="NONE", export_image_format="NONE")
print("HEAD FORWARD OK", A.out, math.ceil(max(abs(a[0]) for a in after)))
