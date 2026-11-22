"""Hand rotation of the approved key poses put back on a clip after the retarget: a correction AFTER the model. Kimodo hits
the key poses' joint positions but not the hands' rotation (knight round 3: hand 2-8 cm from the key, turned 15-176 deg off;
the retarget is faithful, the loss is Kimodo's). Per key and side: the forearm roll that leaves the hand with the POSE's wrist
twist, and the wrist (hand under forearm) that then hits the posed hand, cut to --max-twist / --max-bend (keyhands.py
wrist_from_pose). Between keys the roll and the wrist are spread with a smoothstep; Kimodo's own wrist is not kept (round 7
raw: twist up to 179 deg; keeping it and turning the forearm left 149-158). Joint positions do not move.
Before and after: wrist twist / bend and hand jump as the audit measures them; a WORSE line where the correction pushes one
past its audit limit beyond the uncorrected clip.
blender -b --python pipeline/motion/key_hands.py -- --clip clip.glb --poses poses.glb --frames 0,12,20 --out clip.glb
    --report keyhands.json [--clip-action ai_source] [--poses-action attack] [--no-loop] [--measure-only] [--skeleton X]
Report: per key and side the hand rotation off the pose before/after (deg), and the targets (armature space) for the audit."""
import argparse, json, math, os, sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import keyhands as KH
import skeleton
from collisions import rig_of
from audit_metrics import METRICS

ap = argparse.ArgumentParser(description="Put the key poses' hand rotation back on a retargeted clip.")
ap.add_argument("--clip", required=True); ap.add_argument("--clip-action", default="ai_source")
ap.add_argument("--poses", required=True); ap.add_argument("--poses-action", required=True, help="exact name or its prefix")
ap.add_argument("--frames", required=True, help="key frames (24 fps), the same in the poses and the clip")
ap.add_argument("--out", default=None, help="corrected clip (may be --clip); not written with --measure-only")
ap.add_argument("--report", required=True); ap.add_argument("--no-loop", action="store_true")
ap.add_argument("--measure-only", action="store_true", help="targets and errors only (a prop solver sets the hands later)")
ap.add_argument("--max-bend", type=float, default=80.0, help="deg: wrist bend the correction may reach (audit limit 85)")
ap.add_argument("--max-twist", type=float, default=55.0, help="deg: wrist twist the correction may reach (audit limit 60)")
ap.add_argument("--skeleton", default=None)
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
if not A.measure_only and not A.out: ap.error("--out is required (except with --measure-only)")
KEYS = sorted({int(x) for x in A.frames.split(",")})
Y = (0.0, 1.0, 0.0)   # a pose bone's own axis


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


def q4(q): return np.array([q.w, q.x, q.y, q.z])


def bq(a): return Quaternion([float(x) for x in a])


def hand_q(arm, b): return q4(arm.pose.bones[b].matrix.to_quaternion())


sc = None
arm, act = load(A.poses, A.poses_action); sc = bpy.context.scene
PROF = rig_of(arm, A.skeleton).prof
B = {s[0]: {r: PROF.bone(r, s) for r in ("forearm", "hand")} for s in skeleton.SIDES}
TARGET, POSE_WRIST = {}, {}
for f in KEYS:
    sc.frame_set(f); bpy.context.view_layer.update()
    TARGET[f] = {s: hand_q(arm, B[s]["hand"]) for s in B}
    POSE_WRIST[f] = {s: q4(arm.pose.bones[B[s]["hand"]].matrix_basis.to_quaternion()) for s in B}
print("poses: %s, action %s, keys %s" % (os.path.basename(A.poses), act.name, KEYS))

arm, act = load(A.clip, A.clip_action); sc = bpy.context.scene
f0, f1 = act.frame_range[0], act.frame_range[1]; last = f1 - f0
FC = act.fcurves if hasattr(act, "fcurves") else [c for l in act.layers for st in l.strips for b in st.channelbags for c in b.fcurves]


def errors():
    out = {}
    for f in KEYS:
        sc.frame_set(int(f0) + f); bpy.context.view_layer.update()
        out[f] = {s: round(KH.angle(hand_q(arm, B[s]["hand"]), TARGET[f][s]), 1) for s in B}
    return out


def curves(b):
    path = 'pose.bones["%s"].rotation_quaternion' % b
    ch = {fc.array_index: fc for fc in FC if fc.data_path == path}
    if len(ch) < 4: raise SystemExit("%s: no rotation curves for %s" % (A.clip, b))
    return ch


def basis(b):
    """(times, quats): the bone's rotation at its own key times plus the key frames. The clip keeps Kimodo's 30 fps keys in a
    24 fps scene (one every 0.8 frame), so most key frames fall between keys: they get a key of their own."""
    ch = curves(b); ts = sorted({round(k.co[0], 4) for k in ch[0].keyframe_points} | {float(f0 + f) for f in KEYS})
    qs = [np.array([ch[i].evaluate(t) for i in range(4)]) for t in ts]
    return ts, [q / np.linalg.norm(q) for q in qs]


def write(b, ts, quats):
    """quats at times ts -> the bone's rotation curves (REPLACE keeps each key's interpolation)."""
    ch = curves(b); prev = None
    for t, q in zip(ts, quats):
        q = np.asarray(q, float); q = q / np.linalg.norm(q)
        if prev is not None and np.dot(q, prev) < 0: q = -q    # one hemisphere: curves interpolate component-wise
        prev = q
        for i in range(4): ch[i].keyframe_points.insert(t, float(q[i]), options={"REPLACE"})
    for c in ch.values(): c.update()


STEP_AUDIT = 0.25   # motion_audit.py --step


def wrist_stats():
    """{side: {"twist", "bend"} max deg of the hand under the forearm} and the max hand jump (deg per audit step), as
    motion_audit.py measures wrist_twist / wrist_bend / hand_jump."""
    out = {s: {"twist": 0.0, "bend": 0.0} for s in B}; jump, prev = 0.0, None
    for i in range(int(round(last / STEP_AUDIT)) + 1):
        t = f0 + i * STEP_AUDIT; sc.frame_set(int(t), subframe=t - int(t)); bpy.context.view_layer.update(); now = {}
        for s in B:
            q = q4(arm.pose.bones[B[s]["hand"]].matrix_basis.to_quaternion())
            out[s]["twist"] = max(out[s]["twist"], abs(math.degrees(KH.twist(q, Y)))); out[s]["bend"] = max(out[s]["bend"], KH.swing_deg(q, Y))
            now[s] = hand_q(arm, B[s]["hand"])
        if prev: jump = max(jump, max(KH.angle(now[s], prev[s]) for s in B))
        prev = now
    return {"L": {k: round(v, 1) for k, v in out["L"].items()}, "R": {k: round(v, 1) for k, v in out["R"].items()}, "hand_jump": round(jump, 1)}


BEFORE = errors(); WB = wrist_stats()
# a loop that ends where it starts (retarget_kimodo loop_blend) has its period = the clip's length, else one key step more
sc.frame_set(int(f0)); bpy.context.view_layer.update(); q_first = {s: hand_q(arm, B[s]["hand"]) for s in B}
sc.frame_set(int(f1), subframe=f1 - int(f1)); bpy.context.view_layer.update()
closed = all(KH.angle(hand_q(arm, B[s]["hand"]), q_first[s]) < 1.0 for s in B)
_kt = sorted(k.co[0] for k in curves(B["R"]["hand"])[0].keyframe_points); STEP = float(np.median(np.diff(_kt))) if len(_kt) > 1 else 1.0
LOOP = not A.no_loop; N = last if LOOP and closed else last + STEP
ROLL, WRIST = {s: {} for s in B}, {s: {} for s in B}
if not A.measure_only:
    for s in B:
        fa, hb = B[s]["forearm"], B[s]["hand"]; pfa = arm.pose.bones[fa]; pfa.rotation_mode = "QUATERNION"
        rest = q4((arm.data.bones[fa].matrix_local.to_3x3().inverted() @ arm.data.bones[hb].matrix_local.to_3x3()).to_quaternion())
        ts, base = basis(fa); rel = [t - f0 for t in ts]
        for f in KEYS:
            sc.frame_set(int(f0) + f); bpy.context.view_layer.update()
            ROLL[s][f], w = KH.wrist_from_pose(q4(pfa.matrix.to_quaternion()), TARGET[f][s], rest, POSE_WRIST[f][s], Y)
            WRIST[s][f] = KH.limit_wrist(w, Y, A.max_twist, A.max_bend)
        write(fa, ts, [KH.qmul(q, KH.axis_angle(Y, r)) for q, r in zip(base, KH.roll_track(ROLL[s], N, LOOP, rel))])
        arm.pose.bones[hb].rotation_mode = "QUATERNION"; ts, _ = basis(hb); rel = [t - f0 for t in ts]
        # a slerp between two wrists within the limits can leave them by a little: cut again at every written time
        write(hb, ts, [KH.limit_wrist(q, Y, A.max_twist, A.max_bend) for q in KH.quat_track(WRIST[s], N, LOOP, rel)])
AFTER, WA = (errors(), wrist_stats()) if not A.measure_only else (BEFORE, WB)
LIMIT = {"twist": METRICS["wrist_twist_L"][0], "bend": METRICS["wrist_bend_L"][0], "hand_jump": METRICS["hand_jump"][0]}
WORSE = []   # past the audit limit and beyond the uncorrected clip
for s in B:
    for k in ("twist", "bend"):
        if WA[s][k] > LIMIT[k] and WA[s][k] > WB[s][k] + 0.5:
            WORSE.append("%s wrist %s %.0f -> %.0f deg (limit %d)" % (s, k, WB[s][k], WA[s][k], LIMIT[k]))
if WA["hand_jump"] > LIMIT["hand_jump"] and WA["hand_jump"] > WB["hand_jump"] + 0.5:
    WORSE.append("hand jump %.1f -> %.1f deg (limit %d)" % (WB["hand_jump"], WA["hand_jump"], LIMIT["hand_jump"]))
for f in KEYS:
    print("KEY %2d: hand off the pose L %5.1f -> %5.1f, R %5.1f -> %5.1f deg%s" % (
        f, BEFORE[f]["L"], AFTER[f]["L"], BEFORE[f]["R"], AFTER[f]["R"], "" if A.measure_only else
        " | roll L %+.0f R %+.0f deg, wrist twist L %+.0f R %+.0f, bend L %.0f R %.0f deg" % (
            math.degrees(ROLL["L"][f]), math.degrees(ROLL["R"][f]), *(math.degrees(KH.twist(WRIST[s][f], Y)) for s in "LR"),
            *(KH.swing_deg(WRIST[s][f], Y) for s in "LR"))))
print("WRIST before: twist L %.0f R %.0f, bend L %.0f R %.0f, hand jump %.1f deg%s" % (
    WB["L"]["twist"], WB["R"]["twist"], WB["L"]["bend"], WB["R"]["bend"], WB["hand_jump"], "" if A.measure_only else
    " | after: twist L %.0f R %.0f, bend L %.0f R %.0f, hand jump %.1f deg" % (
        WA["L"]["twist"], WA["R"]["twist"], WA["L"]["bend"], WA["R"]["bend"], WA["hand_jump"])))
for w in WORSE: print("WORSE than the uncorrected clip:", w)
rep = {"clip": os.path.abspath(A.clip), "poses": os.path.abspath(A.poses), "keys": KEYS, "applied": not A.measure_only,
       "loop": LOOP, "period": N, "max_bend": A.max_bend, "max_twist": A.max_twist,
       "targets": {str(f): {s: [round(float(x), 6) for x in TARGET[f][s]] for s in B} for f in KEYS},
       "before": {str(f): BEFORE[f] for f in KEYS}, "after": {str(f): AFTER[f] for f in KEYS},
       "roll_deg": {s: {str(f): round(math.degrees(v), 1) for f, v in ROLL[s].items()} for s in B},
       "wrist_deg": {s: {str(f): {"twist": round(math.degrees(KH.twist(v, Y)), 1), "bend": round(KH.swing_deg(v, Y), 1)}
                         for f, v in WRIST[s].items()} for s in B},
       "wrist_before": WB, "wrist_after": WA, "worse": WORSE}
json.dump(rep, open(A.report, "w", encoding="utf-8"), indent=1)
if not A.measure_only:
    # the keys as they are (30 fps times in a 24 fps scene): default sampling would resample the clip at whole frames
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(A.out), export_format="GLB", export_animations=True, export_force_sampling=False,
                              export_apply=False, export_materials="NONE", export_image_format="NONE")
print("KEY HANDS OK", A.out or "(measured)", "max after: L %.1f R %.1f deg" % (
    max(AFTER[f]["L"] for f in KEYS), max(AFTER[f]["R"] for f in KEYS)))
