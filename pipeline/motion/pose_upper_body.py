"""Upper body from the approved key poses instead of the motion model: the spine above the hips, both shoulders, upper
arms, forearms and hands get the poses' own rotations on the key frames and a Hermite track between them (pose_track.py).
Legs, hips, neck and head stay the clip's. For a fast action with dense keys (a one-handed cut: 9 keys in 38 frames), where
the model folds the arm between the keys: knight round 8, elbow flex 47 -> 89 -> 65 deg in mid-swing, twice rejected.
Motion file `upper_body` (an action without it is not touched; chain.py runs this after the retarget):
    "tangents": {"20": 1.6, "22": 0.25}   speed through a key against Catmull-Rom's: faster into the strike, braking after it
    "breakdowns": {"17": {"wrist_move": [x, y, z], "weapon_toward": [x, y, z]}}   an in-between pose of the weapon arm, built
        here: the wrist moved by that much (m, world) from where the track puts it on that frame, the weapon's blade turned
        toward that world direction, half of the wrist's twist handed to the forearm. Needs the weapon's blade, read from
        the motion file's recipes (swing_arm: `tip`, `edge`; one_hand_weapon: `hand`, `in_hand`, `grip`).
blender -b --python pipeline/motion/pose_upper_body.py -- --clip clip.glb --poses poses.glb --poses-action attack
    --frames 0,8,12,14 --motion motion.json --out clip.glb [--clip-action ai_source] [--no-loop] [--skeleton X]
Hands on the key frames are the poses' against the model's hips, so they sit a little off the poses in the world:
key_hands.py --measure-only reports by how much, and the audit scores it."""
import argparse, json, math, os, sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
for d in ("lib", "recipes"): sys.path.insert(0, os.path.join(HERE, "..", d))
import pose_track as PT
import skeleton
from collisions import rig_of

ap = argparse.ArgumentParser(description="Spine, shoulders, arms and hands of a clip from the approved key poses.")
ap.add_argument("--clip", required=True); ap.add_argument("--clip-action", default="ai_source")
ap.add_argument("--poses", required=True); ap.add_argument("--poses-action", required=True, help="exact name or its prefix")
ap.add_argument("--frames", required=True, help="key frames (24 fps), the same in the poses and the clip")
ap.add_argument("--motion", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--no-loop", action="store_true", help="one-shot action: the last pose is held to the end")
ap.add_argument("--skeleton", default=None)
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
R = json.load(open(A.motion, encoding="utf-8")); UB = R.get("upper_body") or {}
KEYS = sorted({int(x) for x in A.frames.split(",")})
SCALE = {int(k): float(v) for k, v in UB.get("tangents", {}).items()}
BREAK = {int(k): v for k, v in UB.get("breakdowns", {}).items()}
SPLIT = 0.5   # share of a breakdown's wrist twist handed to the forearm roll (all of it on the wrist: 126 deg on the knight)
if set(BREAK) & set(KEYS): raise SystemExit("%s: upper_body.breakdowns on key frames %s: a key pose is already there" % (A.motion, sorted(set(BREAK) & set(KEYS))))


def load(path, action):
    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    acts = sorted(bpy.data.actions, key=lambda a: a.name)
    act = next((a for a in acts if a.name == action), None) or next((a for a in acts if action and a.name.startswith(action)), None)
    if act is None: raise SystemExit("%s: no action %s (there are: %s)" % (path, action, ", ".join(a.name for a in acts)))
    arm.animation_data.action = act
    try: arm.animation_data.action_slot = act.slots[0]
    except (AttributeError, IndexError): pass
    for pb in arm.pose.bones: pb.matrix_basis = Matrix()   # bones without curves here keep another action's pose
    return arm, act


arm, act = load(A.poses, A.poses_action); sc = bpy.context.scene; PROF = rig_of(arm, A.skeleton).prof
ARMS = {s: [PROF.bone(r, s) for r in ("shoulder", "upper_arm", "forearm", "hand") if PROF.has(r, s)] for s in skeleton.SIDES}
BONES = list(PROF.spine) + [b for s in skeleton.SIDES for b in ARMS[s]]
KQ = {}   # (bone, key frame) -> the pose's own rotation (against its parent)
for f in KEYS:
    sc.frame_set(f); bpy.context.view_layer.update()
    for b in BONES: KQ[(b, f)] = np.array(arm.pose.bones[b].matrix_basis.to_quaternion())

arm, act = load(A.clip, A.clip_action); sc = bpy.context.scene; pb = arm.pose.bones
f0, f1 = act.frame_range[0], act.frame_range[1]; TIMES = PT.key_times(f0, f1)
if KEYS[-1] > f1 - f0: raise SystemExit("%s: key frame %d is past the clip's end (%.1f)" % (A.clip, KEYS[-1], f1 - f0))
MW = arm.matrix_world; MW3 = MW.to_3x3(); W2A = MW3.inverted()
def upd(): bpy.context.view_layer.update()


def apply(kq):
    """Every bone's keys through the track, written on TIMES (the bone's other rotation keys go)."""
    bags = [act] if hasattr(act, "fcurves") else [bg for la in act.layers for st in la.strips for bg in st.channelbags]
    for b in BONES:
        ks = sorted(f for (bb, f) in kq if bb == b)
        Q = PT.track([f0 + k for k in ks], [kq[(b, k)] for k in ks], f1, TIMES, {int(f0) + k: v for k, v in SCALE.items()}, not A.no_loop)
        for bag in bags:
            for fc in [c for c in bag.fcurves if c.data_path.startswith('pose.bones["%s"].rotation' % b)]: bag.fcurves.remove(fc)
        pb[b].rotation_mode = "QUATERNION"
        for t, q in zip(TIMES, Q): pb[b].rotation_quaternion = Quaternion(q); pb[b].keyframe_insert("rotation_quaternion", frame=t)


apply(KQ)
if BREAK:
    from swing_arm import grip_frame, weapon_inputs
    try:
        P = weapon_inputs(R); REL = Matrix(grip_frame(P["in_hand"], P["grip"], P["tip"], P["edge"])[0].tolist())
    except (ValueError, KeyError) as e:
        raise SystemExit("%s: upper_body.breakdowns turn the weapon's blade and need a swing_arm recipe in this file (%s)" % (A.motion, e))
    side = P.get("hand", "right").capitalize(); UA, FA, HA = (PROF.bone(r, side) for r in ("upper_arm", "forearm", "hand"))

    def head(n): upd(); return MW @ pb[n].head
    def blade(): upd(); return ((MW @ pb[HA].matrix @ REL).to_3x3() @ Vector((0, 0, 1))).normalized()

    def turn(bone, rot):
        upd(); M = bone.matrix.copy(); hd = M.translation.copy()
        bone.matrix = Matrix.Translation(hd) @ (W2A @ rot @ MW3).to_4x4() @ Matrix.Translation(-hd) @ M

    def reach(goal):
        """Upper arm and forearm so the wrist is at `goal` (Blender's two-bone IK), kept as plain rotations."""
        t = bpy.data.objects.new("wrist_goal", None); sc.collection.objects.link(t); t.location = goal
        c = pb[FA].constraints.new("IK"); c.target = t; c.chain_count = 2
        upd(); keep = {x: pb[x].matrix.copy() for x in (UA, FA)}
        pb[FA].constraints.remove(c); bpy.data.objects.remove(t)
        for x in (UA, FA): pb[x].matrix = keep[x]; upd()

    def wrist():
        q = pb[HA].rotation_quaternion; tw = (math.degrees(2 * math.atan2(q.y, q.w)) + 180) % 360 - 180
        return tw, math.degrees((q @ Quaternion((q.w, 0, q.y, 0)).normalized().inverted()).angle)

    for f, s in sorted(BREAK.items()):
        if not 0 < f < f1 - f0: raise SystemExit("%s: upper_body.breakdowns: frame %d is outside the clip" % (A.motion, f))
        sc.frame_set(int(f0) + f); upd(); h0 = head(HA); hr = (MW @ pb[HA].matrix).to_3x3()
        reach(h0 + Vector(s.get("wrist_move", (0, 0, 0))))
        m = (W2A @ hr).to_4x4(); m.translation = pb[HA].matrix.translation; pb[HA].matrix = m; upd()   # the hand keeps its world rotation
        d0 = blade()
        if "weapon_toward" in s: turn(pb[HA], d0.rotation_difference(Vector(s["weapon_toward"]).normalized()).to_matrix())
        upd(); tw0, bd0 = wrist(); hm = pb[HA].matrix.copy(); roll = round(tw0 * SPLIT)
        pb[FA].rotation_quaternion = pb[FA].rotation_quaternion @ Quaternion((0, 1, 0), math.radians(roll)); upd()
        pb[HA].matrix = hm; upd(); tw1, bd1 = wrist()   # the hand (and the blade) stay put in the world
        for b in (UA, FA, HA): KQ[(b, f)] = np.array(pb[b].rotation_quaternion)
        print("BREAKDOWN %d: wrist moved %.1f cm, blade %s -> %s; wrist twist %.0f -> %.0f, bend %.0f -> %.0f deg (forearm roll %d)" % (
            f, (head(HA) - h0).length * 100, tuple(round(v, 2) for v in d0), tuple(round(v, 2) for v in blade()), tw0, tw1, bd0, bd1, roll))
    apply(KQ)

print("UPPER BODY from the poses: %d bones (%s ... %s), keys %s%s%s, %s" % (
    len(BONES), BONES[0], BONES[-1], KEYS, ", breakdowns %s" % sorted(BREAK) if BREAK else "",
    ", tangents %s" % SCALE if SCALE else "", "one-shot" if A.no_loop else "loop closed on the first pose"))
# the keys as they are (the rest of the clip keeps the model's 30 fps times): default sampling would resample at whole frames
bpy.ops.export_scene.gltf(filepath=os.path.abspath(A.out), export_format="GLB", export_animations=True, export_force_sampling=False,
                          export_apply=False, export_materials="NONE", export_image_format="NONE")
print("UPPER BODY OK", A.out)
