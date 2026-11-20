"""Motion audit (with or without a prop) on the deformed mesh, every 1/4 frame: penetration (prop, hands,
forearms into the body; fingers into the prop), joints (wrists, arm skin twist), smoothness (jumps, loop seam), grip (prop above
the head, hand without contact, loose fingers). Over a limit it renders close-ups (5 sides) at the deepest point.
blender -b --python pipeline/checks/motion_audit.py -- --glb X.glb --action attack --out dir [--prop crossbow] [--limits l.json]
    [--frames 10,45,56] [--no-loop] [--rest-is-normal] [--skeleton mixamo|profile.json]
Limits and where they come from: README, "Quality gates". A metric whose skeleton role is absent is listed in `skipped`."""
import bpy, sys, os, math, json, argparse, re
import numpy as np
from mathutils import Matrix, Vector
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from collisions import dominant, masks, vertices, bvh, depth, joint_angles, labels, body_tree, depths, rig_of, FINGER_PREFIX
import skeleton
import skin
from audit_metrics import METRICS, NEEDS, judge

LOOSE_FINGER = 0.02   # m: a finger whose nearest point is farther from the prop does not hold it
# m: prop inside the upper arms with the stock under the armpit (the butt sits between the arm and the ribs, touching both).
# With the stock on the shoulder the butt sits in the shoulder by design (approved Mixamo shot 7.4 cm): no limit there
UNDER_ARM = 0.015

ap = argparse.ArgumentParser(description="Audit one action of a skinned GLB every 1/4 frame.")
ap.add_argument("--glb", required=True); ap.add_argument("--action", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--prop", default=None, help="name of the prop mesh/bone (from prepare_rig)"); ap.add_argument("--limits", default=None)
ap.add_argument("--step", type=float, default=0.25); ap.add_argument("--no-closeups", action="store_true")
ap.add_argument("--rest-is-normal", action="store_true", help="prop carried where it was modelled (not in the hands)")
ap.add_argument("--frames", default=None, help="only these frames (quick grip try): no smoothness metrics")
ap.add_argument("--no-loop", action="store_true", help="one-shot action: no loop seam metric")
ap.add_argument("--under-arm", action="store_true", help="stock under the armpit (motion aim.butt_push): prop in the upper arms is scored")
ap.add_argument("--skeleton", default=None, help="skeleton profile: built-in name or JSON path (default mixamo)")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
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
RIG = rig_of(arm, A.skeleton, exclude=(A.prop,) if A.prop else ()); PROF = RIG.prof
SKIP = PROF.skipped(NEEDS)   # {metric: reason}: not measured, not scored
LIMITS = {k: v[0] for k, v in METRICS.items() if k not in SKIP}
if A.limits: LIMITS.update({k: v for k, v in json.load(open(A.limits, encoding="utf-8")).items() if k not in SKIP})
B = {s: {r: PROF.bone(r, s) for r in ("forearm", "hand")} for s in skeleton.SIDES}
HEAD = PROF.bone("head")
AW = arm.matrix_world
dom = dominant(body); M = masks(dom, RIG); LAB = labels(dom, RIG)
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
SIDE = np.array([RIG.bone_side(d) for d in dom])
FINGERS = {}   # finger (a chain below the hand) -> vertex indices; named by its first bone without the number
for i in np.where(M["fingers"])[0]: FINGERS.setdefault(re.sub(r"_?\d+$", "", PROF.short(RIG.finger_root[dom[i]])), []).append(i)
HAND = {s: np.where((M["hands"] | M["fingers"]) & (SIDE == s))[0] for s in "LR"}
I_HAND = np.where(M["hands"] & ~M["fingers"])[0][::2]; I_FORE = np.where(M["forearms"])[0][::2]
HEADS0 = {b.name: np.array(AW @ b.head_local) for b in arm.data.bones}
arm.data.pose_position = "REST"; bpy.context.view_layer.update()          # skin twist measured from the rig rest pose (heads from head_local)
CO_REST = vertices(body, bpy.context.evaluated_depsgraph_get()); arm.data.pose_position = "POSE"; bpy.context.view_layer.update()
DOM_S = np.array([str(d) for d in dom]); SEGS = {s: skin.segments(PROF, s) for s in skeleton.SIDES}
SKIN = {s: skin.select(DOM_S, CO_REST, HEADS0, SEGS[s]) for s in skeleton.SIDES} if "skin_twist" not in SKIP else {}
TORSO = PROF.spine[-1]
# fingertips (finger_tip_gap): skin of the last bone of each finger chain the profile lists, thumbs left out (a thumb lying
# along the stock or over the fingers keeps its tip off the surface). A profile without chains (Mixamo's grown finger_*
# bones) has no tips to measure
TIPS = {ch[-1]: np.where(dom == ch[-1])[0] for s_ in skeleton.SIDES for f_, ch in PROF.finger_chains(s_).items() if f_ != "thumb"}
TIPS = {n: ii for n, ii in TIPS.items() if len(ii)}
for k_ in ("finger_tip_gap", "finger_tip_fold"):
    if not TIPS and k_ not in SKIP: SKIP[k_] = "no finger_chains in the skeleton profile"; LIMITS.pop(k_, None); LIM.pop(k_, None)
if A.under_arm and "prop_in_upper_arms" not in SKIP: LIMITS["prop_in_upper_arms"] = UNDER_ARM; LIM["prop_in_upper_arms"] = UNDER_ARM * SCALE
# shoulder skin (skin_tear): faces of the clavicle and the upper part of the upper arm (2 of 3 vertices theirs), rest areas
SHOULDER, SHOULDER_U, TEAR = {}, 0.45, 2.0
if "skin_tear" not in SKIP:
    cr = CO_REST[tris]; ar = np.linalg.norm(np.cross(cr[:, 1] - cr[:, 0], cr[:, 2] - cr[:, 0]), axis=1)
    for s_ in skeleton.SIDES:
        ua, fa, sh = PROF.bone("upper_arm", s_), PROF.bone("forearm", s_), PROF.bone("shoulder", s_)
        a_, b_ = HEADS0[ua], HEADS0[fa]; u_ = (cr.mean(1) - a_) @ (b_ - a_) / ((b_ - a_) @ (b_ - a_))
        sel = (np.isin(dom[tris], [ua, sh]).sum(1) >= 2) & (u_ < SHOULDER_U) & (ar > 0)
        if sel.any(): SHOULDER[s_[0]] = (np.where(sel)[0], ar[sel])
# fingertip folds (finger_tip_fold): faces of each chain's last bone, thumbs too (2 of 3 vertices its), rest normals in
# that bone's rest frame; a face turned > FOLD deg against its bone is folded back
FOLD, TIP_FACES = 120.0, {}
if "finger_tip_fold" not in SKIP:
    cr = CO_REST[tris]; n_ = np.cross(cr[:, 1] - cr[:, 0], cr[:, 2] - cr[:, 0]); ln = np.linalg.norm(n_, axis=1)
    for s_ in skeleton.SIDES:
        for ch in PROF.finger_chains(s_).values():
            sel = (np.sum(dom[tris] == ch[-1], 1) >= 2) & (ln > 0)
            if sel.any(): TIP_FACES[ch[-1]] = (np.where(sel)[0], n_[sel] / ln[sel, None])
UPPER = np.isin(dom, PROF.bones("upper_arm"))
GRIP_FINGERS = [b.name for b in arm.pose.bones if b.name.startswith(FINGER_PREFIX) or (b.name in RIG.fingers and (dom == b.name).any())]


def rr(n): return arm.data.bones[n].matrix_local.to_3x3().normalized()
def pr(n): return arm.pose.bones[n].matrix.to_3x3().normalized()
def head(n): return AW @ arm.pose.bones[n].matrix.translation
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

    if SHOULDER:   # shoulder skin torn into long flat facets: faces grown over TEAR x their rest area
        for s_, (fi, a0) in SHOULDER.items():
            c_ = co[tris[fi]]; a1 = np.linalg.norm(np.cross(c_[:, 1] - c_[:, 0], c_[:, 2] - c_[:, 0]), axis=1)
            v_ = round(float(a0[a1 > TEAR * a0].sum() / a0.sum()), 3)
            if v_ > row.get("skin_tear", -1): row["skin_tear"] = v_; where["skin_tear"] = [float(x) for x in c_.mean((0, 1))]; side["skin_tear"] = s_
    if TIP_FACES:   # fingertip skin folded back over itself against its own bone
        for n, (fi, n0) in TIP_FACES.items():
            Rb = np.array((AW @ arm.pose.bones[n].matrix @ arm.data.bones[n].matrix_local.inverted() @ AW.inverted()).to_3x3())
            c_ = co[tris[fi]]; n1 = np.cross(c_[:, 1] - c_[:, 0], c_[:, 2] - c_[:, 0])
            n1 /= np.maximum(np.linalg.norm(n1, axis=1, keepdims=True), 1e-12)
            v_ = round(float(np.mean(np.sum((n0 @ Rb.T) * n1, 1) < math.cos(math.radians(FOLD)))), 3)
            if v_ > row.get("finger_tip_fold", -1):
                row["finger_tip_fold"] = v_; row["_finger_tip_fold"] = n; where["finger_tip_fold"] = [float(x) for x in c_.mean((0, 1))]
                side["finger_tip_fold"] = SIDE[tris[fi[0], 0]]
    measure("hands", co[I_HAND], I_HAND)
    measure("forearms", co[I_FORE], I_FORE)
    if prop:
        pc = vertices(prop, dg)
        PS = pc[rng.choice(len(pc), min(700, len(pc)), replace=False)]
        measure("prop", PS)
        if UPPER.any() and "prop_in_upper_arms" not in SKIP:   # the body tree leaves the arms out: a second one with the upper arms
            lab2 = LAB.copy(); lab2[UPPER] = "upper_arms"; T2, R2 = body_tree(co, tris, lab2)
            d_ = depths(T2, R2, PS).get("upper_arms")
            if d_: row["prop_in_upper_arms"] = round(d_[0], 4); where["prop_in_upper_arms"] = [float(x) for x in d_[1]]
        PB = bvh(pc, ptris)
        if M["fingers"].any() and "fingers_in_prop" not in SKIP:
            d, i = depth(PB, co[M["fingers"]])
            row["fingers_in_prop"] = round(d, 4)
            if i >= 0: where["fingers_in_prop"] = [float(x) for x in co[M["fingers"]][i]]
        cen = pc.mean(0)
        if IN_HANDS:
            dist = lambda ii: min(PB.find_nearest(Vector(co[j]))[3] for j in ii)
            if "prop_above_head" not in SKIP: row["prop_above_head"] = round(max(0.0, float(cen[2] - co[LAB == "head"][:, 2].max())), 4)
            for s in "LR":
                if len(HAND[s]) and "hand_to_prop_" + s not in SKIP: row["hand_to_prop_" + s] = round(dist(HAND[s][::2]), 4)
            if FINGERS and "loose_fingers" not in SKIP:
                loose = [n for n, ii in FINGERS.items() if dist(ii[::2]) > LOOSE_FINGER * SCALE]
                row["loose_fingers"] = round(len(loose) / len(FINGERS), 2); row["_loose_fingers"] = loose
            if TIPS and "finger_tip_gap" not in SKIP:
                gaps = {n: dist(ii) for n, ii in TIPS.items()}
                n_ = max(gaps, key=gaps.get); row["finger_tip_gap"] = round(gaps[n_], 4); row["_finger_tip_gap"] = n_
                row["_finger_tip_gaps"] = {n: round(g, 3) for n, g in gaps.items()}
                where["finger_tip_gap"] = [float(x) for x in co[TIPS[n_]].mean(0)]; side["finger_tip_gap"] = SIDE[TIPS[n_][0]]
    for s, k in (("Left", "L"), ("Right", "R")):
        bend, tw = joint_angles(rr(B[s]["forearm"]), rr(B[s]["hand"]), pr(B[s]["forearm"]), pr(B[s]["hand"]))
        row["wrist_bend_" + k] = round(bend, 1); row["wrist_twist_" + k] = round(abs(tw), 1)
    if SKIN and t >= f0:          # arm skin twist relative to the torso (skin.py)
        Rt = np.array((AW @ arm.pose.bones[TORSO].matrix @ arm.data.bones[TORSO].matrix_local.inverted() @ AW.inverted()).to_3x3())
        for s_, seg in SKIN.items():
            for a_, end_, _ in SEGS[s_]:
                if a_ not in seg: continue
                b_, r_ = skin.twist(CO_REST, co, seg[a_], HEADS0[a_], HEADS0[end_], np.array(head(a_)), np.array(head(end_)), Rt)
                for kk, v_ in (("skin_twist", abs(b_)), ("skin_spread", round(r_, 2))):
                    if v_ > row.get(kk, -1): row[kk] = v_; where[kk] = [float(x) for x in co[seg[a_]].mean(0)]; side[kk] = s_[0]
    row["_where"] = where; row["_side"] = side
    if t < f0:
        rest_row = row; continue
    now = {"L": head(B["Left"]["forearm"]), "R": head(B["Right"]["forearm"]), "p": Vector(cen) if prop else None,
           "qL": pr(B["Left"]["hand"]).to_quaternion(), "qR": pr(B["Right"]["hand"]).to_quaternion(), "qH": pr(HEAD).to_quaternion(),
           "qP": arm.pose.bones[A.prop].matrix.to_quaternion() if prop and A.prop in arm.pose.bones else None,
           # the finger bones the grip solver animates: finger_* or the rig's own skinned fingers (rig fingers without skin
           # - a Mixamo template's - stay at rest)
           "fing": {n: arm.pose.bones[n].matrix_basis.to_quaternion() for n in GRIP_FINGERS}
           if "finger_jump" not in SKIP else {}}
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
errors, scores, score, score_area = judge(samples, LIM, GROUP)
maxima = {k: max(r.get(k, 0) for r in samples) for k in METRICS if k not in SKIP}
report = {"result": "OK" if not errors else "FAIL", "score": score, "scores": scores,
          "score_area": score_area, "height_m": round(H, 3), "errors": errors,
          "maxima": maxima, "rest": {k: rest_row.get(k, 0) for k in maxima}, "limits": {k: round(v, 4) for k, v in LIM.items()},
          "no_limit": [k for k, v in LIMITS.items() if v is None], "frames": FR, "skeleton": PROF.name, "skipped": SKIP}
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
if SKIP: print("  skipped:", "; ".join("%s (%s)" % kv for kv in SKIP.items()))

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
