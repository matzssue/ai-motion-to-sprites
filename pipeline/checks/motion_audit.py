"""Motion audit (with or without a prop) on the deformed mesh, every 1/4 frame: penetration (prop, hands,
forearms into the body; fingers into the prop), joints (wrists, arm skin twist), smoothness (jumps, loop seam), grip (prop above
the head, hand without contact, loose fingers). Over a limit it renders close-ups (5 sides) at the deepest point.
blender -b --python pipeline/checks/motion_audit.py -- --glb X.glb --action attack --out dir [--prop crossbow] [--limits l.json]
    [--frames 10,45,56] [--no-loop] [--rest-is-normal]
Limits and where they come from: README, "Quality gates"."""
import bpy, sys, os, math, json, argparse, re
import numpy as np
from mathutils import Matrix, Vector
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from collisions import dominant, masks, vertices, bvh, depth, joint_angles, labels, body_tree, depths, bone_side, FINGER_PREFIX
import skin

# (limit, unit, group); "m" = metres for a ~1.8 m character (scaled by height), "deg" = degrees, "frac" = 0..1;
# jumps per 1/4 frame. Limit None = reported only (no bad sample yet to calibrate against).
METRICS = {
    "prop_in_head": (0.005, "m", "penetration"), "prop_in_torso": (0.015, "m", "penetration"),
    "prop_in_legs": (0.015, "m", "penetration"), "prop_in_clavicles": (0.03, "m", "penetration"),
    "hands_in_head": (0.005, "m", "penetration"), "hands_in_torso": (0.02, "m", "penetration"),
    "forearms_in_head": (0.01, "m", "penetration"), "forearms_in_torso": (0.045, "m", "penetration"),
    "fingers_in_prop": (0.008, "m", "penetration"),
    "wrist_bend_L": (85, "deg", "joints"), "wrist_bend_R": (85, "deg", "joints"),
    "wrist_twist_L": (60, "deg", "joints"), "wrist_twist_R": (60, "deg", "joints"),
    # elbow: raw Kimodo 1.6 cm; 0.08 let through 15 cm per frame
    "elbow_jump": (0.03, "m", "smoothness"), "prop_jump": (0.10, "m", "smoothness"),
    # raw Kimodo: hand up to 4.8 deg, fingers 0 deg. Per-frame grip choice: hand 15 deg, fingers 24 deg
    "hand_jump": (8, "deg", "smoothness"), "finger_jump": (6, "deg", "smoothness"),
    "head_jump": (4, "deg", "smoothness"), "prop_rot_jump": (None, "deg", "smoothness"),
    # seam: last frame vs first. Library walk 1.8 deg / 1.4 cm; a 26 deg head pop was reported by eye
    "loop_seam_deg": (15, "deg", "smoothness"), "loop_seam_m": (0.12, "m", "smoothness"),
    # with the grip solver 0-0.1 cm, without it (raw Kimodo) 50-62 cm
    "hand_to_prop_L": (0.03, "m", "grip"), "hand_to_prop_R": (0.03, "m", "grip"),
    "prop_above_head": (None, "m", "grip"), "loose_fingers": (None, "frac", "grip"),
    # growth of body mesh edges vs rest: a wrong bone weight gives a "stick" (a claw weighted to the foot: 2 cm -> 85 cm).
    # Walk: broken rig 94 cm, fixed 4; a rag between the legs 18 cm. A length ratio did not separate them (short decimated edges)
    "stretch": (0.30, "m", "joints"),
    # arm skin "candy wrapper" twist (skin.py): broken overhead swing 210-260 deg / spread 0.45-0.80; approved up to 60 / 0.41
    "skin_twist": (skin.TWIST_MAX, "deg", "joints"), "skin_spread": (skin.SPREAD_MAX, "frac", "joints"),
}
LOOSE_FINGER = 0.02   # m: a finger whose nearest point is farther from the prop does not hold it

ap = argparse.ArgumentParser(description="Audit one action of a skinned GLB every 1/4 frame.")
ap.add_argument("--glb", required=True); ap.add_argument("--action", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--prop", default=None, help="name of the prop mesh/bone (from prepare_rig)"); ap.add_argument("--limits", default=None)
ap.add_argument("--step", type=float, default=0.25); ap.add_argument("--no-closeups", action="store_true")
ap.add_argument("--rest-is-normal", action="store_true", help="prop carried where it was modelled (not in the hands)")
ap.add_argument("--frames", default=None, help="only these frames (quick grip try): no smoothness metrics")
ap.add_argument("--no-loop", action="store_true", help="one-shot action: no loop seam metric")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
LIMITS = {k: v[0] for k, v in METRICS.items()}
if A.limits: LIMITS.update(json.load(open(A.limits, encoding="utf-8")))
UNIT = {k: v[1] for k, v in METRICS.items()}; GROUP = {k: v[2] for k, v in METRICS.items()}
os.makedirs(A.out, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=A.glb)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
arm.animation_data.action = bpy.data.actions[A.action]
# bones without curves in this action keep the pose of another action in the file (walk fingers broke a shot by 2 cm): start from rest
for _pb in arm.pose.bones: _pb.matrix_basis = Matrix()
skinned = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
prop = next((o for o in skinned if A.prop and o.name.startswith(A.prop)), None)
body = max((o for o in skinned if o is not prop), key=lambda o: len(o.data.vertices))
for o in bpy.data.objects:
    if o.type == "MESH" and o not in skinned: o.hide_render = True
P = next((b.name.split(":")[0] + ":" for b in arm.data.bones if ":" in b.name), "")
AW = arm.matrix_world
dom = dominant(body); M = masks(dom); LAB = labels(dom)
tris = np.array([p.vertices[:3] for p in body.data.polygons])
EDGES = np.array([e.vertices[:] for e in body.data.edges])
ptris = np.array([p.vertices[:3] for p in prop.data.polygons]) if prop else None
sc = bpy.context.scene
f0, f1 = (int(v) for v in arm.animation_data.action.frame_range)
dg0 = bpy.context.evaluated_depsgraph_get()
co_rest = vertices(body, dg0)
EDGE_L0 = np.linalg.norm(co_rest[EDGES[:, 0]] - co_rest[EDGES[:, 1]], axis=1)
H = float(co_rest[:, 2].max() - co_rest[:, 2].min())
SCALE = H / 1.8
LIM = {k: (v * SCALE if UNIT[k] == "m" else v) for k, v in LIMITS.items() if v is not None}
IN_HANDS = prop is not None and not A.rest_is_normal
SIDE = np.array([bone_side(d) for d in dom])
FINGERS = {}   # finger -> vertex indices (`finger_R0_1` and `LeftHandIndex1` -> one finger)
for i in np.where(M["fingers"])[0]: FINGERS.setdefault(re.sub(r"_?\d+$", "", dom[i]), []).append(i)
HAND = {s: np.where((M["hands"] | M["fingers"]) & (SIDE == s))[0] for s in "LR"}
I_HAND = np.where(M["hands"] & ~M["fingers"])[0][::2]; I_FORE = np.where(M["forearms"])[0][::2]
HEADS0 = {b.name[len(P):]: np.array(AW @ b.head_local) for b in arm.data.bones if b.name.startswith(P)}
arm.data.pose_position = "REST"; bpy.context.view_layer.update()          # skin twist measured from the rig rest pose (heads from head_local)
CO_REST = vertices(body, bpy.context.evaluated_depsgraph_get()); arm.data.pose_position = "POSE"; bpy.context.view_layer.update()
DOM_S = np.array([str(d) for d in dom]); SKIN = {s: skin.select(DOM_S, CO_REST, HEADS0, s) for s in ("Left", "Right")}
TORSO = next((n for n in ("Spine2", "Spine1", "Spine") if P + n in arm.data.bones), None)


def rr(n): return arm.data.bones[P + n].matrix_local.to_3x3().normalized()
def pr(n): return arm.pose.bones[P + n].matrix.to_3x3().normalized()
def head(n): return AW @ arm.pose.bones[P + n].matrix.translation
def ang(a, b): return (lambda x: min(x, 360 - x))(math.degrees(a.rotation_difference(b).angle))


rng = np.random.default_rng(0)
samples, prev, first = [], None, None
FR = [float(x) for x in A.frames.split(",")] if A.frames else None
times = [-1.0] + (FR if FR else [f0 + i * A.step for i in range(int(round((f1 - f0) / A.step)) + 1)])
# sample -1 = rest pose: what is fused in the model itself (e.g. a prop on the back), not in the motion
arm.data.pose_position = "REST"
rest_row = {}
for t in times:
    if t >= f0:
        arm.data.pose_position = "POSE"; sc.frame_set(int(t), subframe=t - int(t))
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    co = vertices(body, dg)
    T, REGF = body_tree(co, tris, LAB)
    row = {"t": t}; where = {}; side = {}
    eg = np.linalg.norm(co[EDGES[:, 0]] - co[EDGES[:, 1]], axis=1) - EDGE_L0; ie = int(eg.argmax())
    row["stretch"] = round(float(eg[ie]), 4); where["stretch"] = [float(x) for x in co[EDGES[ie, 0]]]

    def measure(what, pts, idx=None):
        for r, (d, p, i) in depths(T, REGF, pts).items():
            k = "%s_in_%s" % (what, r)
            if d > row.get(k, 0):
                row[k] = round(d, 4); where[k] = [float(x) for x in p]
                if idx is not None: side[k] = SIDE[idx[i]]

    measure("hands", co[I_HAND], I_HAND)
    measure("forearms", co[I_FORE], I_FORE)
    if prop:
        pc = vertices(prop, dg)
        measure("prop", pc[rng.choice(len(pc), min(700, len(pc)), replace=False)])
        PB = bvh(pc, ptris)
        if M["fingers"].any():
            d, i = depth(PB, co[M["fingers"]])
            row["fingers_in_prop"] = round(d, 4)
            if i >= 0: where["fingers_in_prop"] = [float(x) for x in co[M["fingers"]][i]]
        cen = pc.mean(0)
        if IN_HANDS:
            dist = lambda ii: min(PB.find_nearest(Vector(co[j]))[3] for j in ii)
            row["prop_above_head"] = round(max(0.0, float(cen[2] - co[LAB == "head"][:, 2].max())), 4)
            for s in "LR":
                if len(HAND[s]): row["hand_to_prop_" + s] = round(dist(HAND[s][::2]), 4)
            if FINGERS:
                loose = [n for n, ii in FINGERS.items() if dist(ii[::2]) > LOOSE_FINGER * SCALE]
                row["loose_fingers"] = round(len(loose) / len(FINGERS), 2); row["_loose_fingers"] = loose
    for s, k in (("Left", "L"), ("Right", "R")):
        bend, tw = joint_angles(rr(s + "ForeArm"), rr(s + "Hand"), pr(s + "ForeArm"), pr(s + "Hand"))
        row["wrist_bend_" + k] = round(bend, 1); row["wrist_twist_" + k] = round(abs(tw), 1)
    if TORSO and t >= f0:          # arm skin twist relative to the torso (skin.py)
        Rt = np.array((AW @ arm.pose.bones[P + TORSO].matrix @ arm.data.bones[P + TORSO].matrix_local.inverted() @ AW.inverted()).to_3x3())
        for s_, seg in SKIN.items():
            for k_, end_, _ in skin.SEGMENTS:
                if s_ + k_ not in seg: continue
                b_, r_ = skin.twist(CO_REST, co, seg[s_ + k_], HEADS0[s_ + k_], HEADS0[s_ + end_], np.array(head(s_ + k_)), np.array(head(s_ + end_)), Rt)
                for kk, v_ in (("skin_twist", abs(b_)), ("skin_spread", round(r_, 2))):
                    if v_ > row.get(kk, -1): row[kk] = v_; where[kk] = [float(x) for x in co[seg[s_ + k_]].mean(0)]; side[kk] = s_[0]
    row["_where"] = where; row["_side"] = side
    if t < f0:
        rest_row = row; continue
    now = {"L": head("LeftForeArm"), "R": head("RightForeArm"), "p": Vector(cen) if prop else None,
           "qL": pr("LeftHand").to_quaternion(), "qR": pr("RightHand").to_quaternion(), "qH": pr("Head").to_quaternion(),
           "qP": arm.pose.bones[A.prop].matrix.to_quaternion() if prop and A.prop in arm.pose.bones else None,
           "fing": {b.name: b.matrix_basis.to_quaternion() for b in arm.pose.bones if b.name.startswith(FINGER_PREFIX)}}
    if prev and not FR:
        row["hand_jump"] = round(max(ang(now[k], prev[k]) for k in ("qL", "qR")), 1)
        row["head_jump"] = round(ang(now["qH"], prev["qH"]), 1)
        if now["fing"]: row["finger_jump"] = round(max(ang(q, prev["fing"][n]) for n, q in now["fing"].items()), 1)
        row["elbow_jump"] = round(max((now[k] - prev[k]).length for k in ("L", "R")), 4)
        if prop: row["prop_jump"] = round((now["p"] - prev["p"]).length, 4)
        if now["qP"]: row["prop_rot_jump"] = round(ang(now["qP"], prev["qP"]), 1)
    prev = now; first = first or now
    samples.append(row)
# loop seam: last frame vs first (Kimodo does not return to the start pose: a head popped by 26 deg)
if not FR and not A.no_loop and len(samples) > 1:
    samples[-1]["loop_seam_deg"] = round(max(ang(prev[k], first[k]) for k in ("qL", "qR", "qH")), 1)
    samples[-1]["loop_seam_m"] = round(max((prev[k] - first[k]).length for k in ("L", "R")), 4)

# penetration already fused into the model (rest) raises the limit only with --rest-is-normal (prop carried where modelled)
if A.rest_is_normal:
    for k in LIM:
        if GROUP[k] == "penetration" and rest_row.get(k, 0) > 0: LIM[k] = LIM[k] + rest_row[k]
errors = {}
for k, lim in LIM.items():
    bad = [r for r in samples if r.get(k, 0) > lim]
    if bad:
        worst = max(bad, key=lambda r: r[k])
        errors[k] = {"limit": round(lim, 4), "max": worst[k], "at_frame": worst["t"], "samples": len(bad),
                     "share": round(len(bad) / len(samples), 2), "range": [bad[0]["t"], bad[-1]["t"]],
                     "where": worst["_where"].get(k), "side": worst["_side"].get(k),
                     # area: mean excess over all samples, so one frame does not dominate (the score takes the maximum)
                     "area": round(sum(r[k] / lim - 1 for r in bad) / len(samples), 3)}
maxima = {k: max(r.get(k, 0) for r in samples) for k in METRICS}
scores = {}
for k, v in errors.items(): scores[GROUP[k]] = round(scores.get(GROUP[k], 0) + v["max"] / max(v["limit"], 1e-9) - 1, 2)
score = round(sum(v["max"] / max(v["limit"], 1e-9) - 1 for v in errors.values()), 2)   # 0 = OK; used to pick a sample
report = {"result": "OK" if not errors else "FAIL", "score": score, "scores": scores,
          "score_area": round(sum(v["area"] for v in errors.values()), 3), "height_m": round(H, 3), "errors": errors,
          "maxima": maxima, "rest": {k: rest_row.get(k, 0) for k in METRICS}, "limits": {k: round(v, 4) for k, v in LIM.items()},
          "no_limit": [k for k, v in LIMITS.items() if v is None], "frames": FR}
json.dump(report, open(os.path.join(A.out, "audit.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(samples, open(os.path.join(A.out, "audit_samples.json"), "w", encoding="utf-8"), ensure_ascii=False)
print("AUDIT %s (height %.2f m, %d samples)" % (report["result"], H, len(samples)))
print("  rest:", {k: v for k, v in report["rest"].items() if v and GROUP[k] == "penetration"})
print("  score: %.2f" % score, " ".join("%s %.2f" % kv for kv in scores.items()), "| area %.3f" % report["score_area"])


def fmt(k, v): return "%6.1f%s" % ((v * 100, " cm") if UNIT[k] == "m" else (v * 100, "%") if UNIT[k] == "frac" else (v, " deg"))


for k, v in sorted(errors.items(), key=lambda kv: -kv[1]["max"] / max(kv[1]["limit"], 1e-9)):
    print("  FAIL %-22s max %s (limit %s) at fr. %.2f, fr. %.2f-%.2f, %d%% of samples%s" % (
        k, fmt(k, v["max"]), fmt(k, v["limit"]).strip(), v["at_frame"], v["range"][0], v["range"][1], round(100 * v["share"]),
        {"L": ", left", "R": ", right"}.get(v["side"], "")))
print("  no limit:", ", ".join("%s %s" % (k, fmt(k, maxima[k]).strip()) for k in report["no_limit"] if maxima[k]))

# close-ups of the worst spots
if errors and not A.no_closeups:
    import gpu_queue; gpu_queue.acquire("motion_audit.py", None)  # Eevee on the GPU
    sc.render.engine = "BLENDER_EEVEE"; sc.render.film_transparent = True
    sc.render.resolution_x = sc.render.resolution_y = 480; sc.view_settings.view_transform = "Standard"
    w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True; w.node_tree.nodes["Background"].inputs[1].default_value = 3.0
    for rot in ((50, 0, 30), (60, 0, 200)):
        s_ = bpy.data.objects.new("s", bpy.data.lights.new("s", "SUN")); s_.data.energy = 4
        s_.rotation_euler = [math.radians(r) for r in rot]; sc.collection.objects.link(s_)
    cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = "ORTHO"; cam.data.ortho_scale = 0.45 * SCALE
    for k, v in errors.items():
        if not v.get("where"): continue
        tt = v["at_frame"]; sc.frame_set(int(tt), subframe=tt - int(tt))
        tg = Vector(v["where"])
        for nm, yaw in (("front", 0), ("right", -90), ("three_quarter", -40), ("left", 90), ("top", None)):
            d = Vector((0.001, 0, 1)) if yaw is None else Vector((math.sin(math.radians(yaw)), -math.cos(math.radians(yaw)), 0.25))
            d.normalize(); cam.location = tg + d * 4; cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = os.path.join(A.out, "closeups", "%s_fr%.2f_%s.png" % (k, tt, nm))
            bpy.ops.render.render(write_still=True)
    print("closeups:", os.path.join(A.out, "closeups"))
