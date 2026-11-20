"""Prop (cut out by prepare_rig) in both hands on an AI motion: a prop pose searched without body collisions,
both arms by analytic IK to the grip from the motion file (grip roll and elbow chosen for the wrist and for collisions),
fingers wrapped around the stock, torso recoil. The result is checked by motion_audit.py - never shown without it.
blender -b --python pipeline/motion/prop_in_hands.py -- --glb merged.glb --rig-data rig_ai_data.json --motion <motion>.json --out out.glb
    [--skeleton mixamo|profile.json]   bones by role; a skeleton without fingers: no finger wrap (reported as skipped)
    [--frames 10,45,56]  quick grip try: only these frames, best grip for each on its own (no path or smoothing in time)
Blender's IK does not work on rigs from GLB (bone lengths are meaningless), hence IK from bone heads."""
import bpy, sys, os, math, json, argparse, time
import numpy as np
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from collisions import dominant, labels, vertices, inside, joint_angles, rig_of, FINGER_PREFIX
from grip_words import grip_from_words, grip_in_words

ap = argparse.ArgumentParser(description="Put the prop in both hands: prop pose, two-arm IK, finger wrap, recoil.")
ap.add_argument("--glb", required=True); ap.add_argument("--rig-data", required=True)
ap.add_argument("--motion", required=True); ap.add_argument("--out", required=True); ap.add_argument("--frames", default=None)
ap.add_argument("--skeleton", default=None, help="skeleton profile: built-in name or JSON path (default mixamo)")
A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
MO = json.load(open(A.motion, encoding="utf-8")); GP = MO["grip"]
RD = json.load(open(A.rig_data, encoding="utf-8"))
FWD, UP, RIGHT = Vector((0, -1, 0)), Vector((0, 0, 1)), Vector((-1, 0, 0))   # character faces -Y

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=A.glb)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
act = bpy.data.actions[MO["action"]]; arm.animation_data.action = act
# bones without curves in this action keep the pose of another action in the file (walk fingers broke a shot by 2 cm): start from rest
for _pb in arm.pose.bones: _pb.matrix_basis = Matrix()
skinned = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
PN = RD["prop"]["name"]
prop = next(o for o in skinned if o.name.startswith(PN))
body = max((o for o in skinned if o is not prop), key=lambda o: len(o.data.vertices))
RIG = rig_of(arm, A.skeleton, exclude=(PN,)); PROF = RIG.prof; P = PROF.prefix
BN = {s: {r: PROF.bone(r, s) for r in ("upper_arm", "forearm", "hand")} for s in ("Left", "Right")}
f0, f1 = (int(v) for v in act.frame_range); all_frames = list(range(f0, f1 + 1))
frames = [int(x) for x in A.frames.split(",")] if A.frames else all_frames   # frames on which the prop is placed
sc = bpy.context.scene; FPS = sc.render.fps
AW = arm.matrix_world; AWi = AW.inverted(); S = AW.to_scale()[0]
PALM = GP["palm_center"]


def pb(n): return arm.pose.bones[n] if n in arm.pose.bones else arm.pose.bones[P + n]
def bone(n): return arm.data.bones[n] if n in arm.data.bones else arm.data.bones[P + n]
def wmat(n): return AW @ pb(n).matrix
def wrot(n): return wmat(n).to_3x3().normalized()
def head(n): return wmat(n).translation.copy()
def rest_rot(n): return (AW @ bone(n).matrix_local).to_3x3().normalized()


def setw(n, R, h=None, loc=False):
    M = R.to_4x4() @ Matrix.Scale(S, 4); M.translation = h if h is not None else head(n)
    b = pb(n); b.matrix = AWi @ M
    if not loc: b.location = (0, 0, 0)
    bpy.context.view_layer.update()


def keyb(n, f, loc=False):
    pb(n).keyframe_insert("rotation_quaternion", frame=f)
    if loc: pb(n).keyframe_insert("location", frame=f)


def frame3(f, u):
    f = f.normalized(); u = (u - f * u.dot(f)).normalized()
    return Matrix((f, u.cross(f), u)).transposed()


for b in arm.pose.bones: b.rotation_mode = "QUATERNION"

# ---------- prop: frame, stock radius ----------
Cr = Matrix(RD["prop"]["frame_world"]); CR_IN_BONE = Matrix(RD["prop"]["frame_in_bone"])
Lc = np.array([tuple(Cr.inverted() @ (prop.matrix_world @ v.co)) for v in prop.data.vertices])
rad = np.linalg.norm(Lc[:, 1:], axis=1)
stockm = rad < GP["stock_radius_max"]
BUTT = float(Lc[rad < GP["stock_radius_max"] + 0.02, 0].min())


def r_at(x):
    m = stockm & (np.abs(Lc[:, 0] - x) < 0.03)
    # median: the 90th percentile caught the string and nut (left: 6.8 cm), the hand stood too far and the fingers did not reach
    return float(np.percentile(rad[m], 50)) if m.any() else 0.035


# ---------- grip: character words <-> vectors in the prop frame (X forward along the stock, Y to the character's LEFT, Z up) ----------
SIDE_NAME = {"Right": "right", "Left": "left"}


GR = {"Right": grip_from_words(GP["right"]), "Left": grip_from_words(GP["left"])}
for s_ in GR: print("grip %s: %s" % (SIDE_NAME[s_], grip_in_words(GR[s_], BUTT)))
RS = {s: r_at(GR[s]["x"]) for s in GR}
print("stock: butt %.3f, radius at grips R %.3f / L %.3f" % (BUTT, RS["Right"], RS["Left"]))
# fingers wrap around the real surface: a stock is not a cylinder (left hand: 7 cm down, 3-5 cm to the sides);
# a cylinder radius kept the left claws 5-16 cm from the stock
PBVH = BVHTree.FromPolygons([Vector(v) for v in Lc], [tuple(q.vertices) for q in prop.data.polygons])
# the own skeleton's long fingers wrap on the stock alone (faces within stock_radius_max of the axis): on the whole prop
# Kusznik's left fingers (grip 33 cm along it, by the bow mount) hooked round the string and the bow 8-12 cm off the axis
STOCK_F = [tuple(q.vertices) for q in prop.data.polygons if stockm[list(q.vertices)].all()]
PBVH_STOCK = BVHTree.FromPolygons([Vector(v) for v in Lc], STOCK_F) if STOCK_F else PBVH


def set_prop(C4, f):
    pb(PN).matrix = AWi @ (C4 @ CR_IN_BONE.inverted())
    bpy.context.view_layer.update(); keyb(PN, f, loc=True)


# ---------- hands and fingers from the rig ----------
NPALM = {s: Vector(RD["palm"][s]["local_normal"]) for s in RD["palm"]}
hand_rest = {s: AW @ bone(BN[s]["hand"]).matrix_local for s in ("Left", "Right")}
FING = {}
# bones the finger wrap animates: finger_* grown by prepare_rig, or the rig's own finger chains it kept (own skeleton)
FING_NAMES = {n for chains in RD["fingers"].values() for ch in chains for n in ch}
if RD["fingers"] and not PROF.has("fingers"): print("fingers: skipped (skeleton '%s' has no fingers): no finger wrap" % PROF.name)


def chain_end(n):
    """Where a finger chain ends: its leaf child (the own skeleton's *_end bone); a GLB keeps no bone tails."""
    b = bone(n); return b.children[0].head_local if b.children else b.tail_local


for s, chains in (RD["fingers"] if PROF.has("fingers") else {}).items():
    FING[s] = [([AW @ bone(n).head_local for n in ch] + [AW @ (chain_end(ch[-1]) if not ch[0].startswith(FINGER_PREFIX)
                                                               else bone(ch[-1]).tail_local)], ch, k in RD["thumbs"].get(s, []))
               for k, ch in enumerate(chains)]
# the rig's own finger chains bend about an axis fixed in each bone (the own skeleton: local X, its Z is the palm normal),
# carried by the bones above it. With one axis from the hand's palm normal for every bone, a finger bent ~90 deg at the
# knuckle points along that normal, the next axis degenerates and the rest of the finger stood up beside the stock
# (Kusznik). The grown finger_* bones (Mixamo template) keep the hand's palm normal: their wrap is approved as it is.
CURL, SPREAD = {}, {}
for s, fl in FING.items():
    n_rest = (hand_rest[s].to_3x3().normalized() @ Vector(RD["palm"][s]["local_normal"])).normalized()
    for J, names, thumb in fl:
        if names[0].startswith(FINGER_PREFIX): continue
        for b in range(3):
            ax = (J[b + 1] - J[b]).normalized().cross(n_rest)
            if ax.length > 1e-6: CURL[names[b]] = (rest_rot(names[b]).transposed() @ ax).normalized()
        # spread axis of the first bone: the palm normal in that bone's frame (the own skeleton: local Z)
        if not names[0].startswith(FINGER_PREFIX): SPREAD[names[0]] = (rest_rot(names[0]).transposed() @ n_rest).normalized()


# knuckles (finger bases without the thumb) in the hand bone frame, from the rest pose
KOFF = {s: hand_rest[s].to_3x3().normalized().transposed() @ (sum((J[0] for J, _, k in FING[s] if not k), Vector())
        / sum(1 for *_, k in FING[s] if not k) - hand_rest[s].translation) for s in FING}
print("knuckles in hand frame:", {s: tuple(round(x, 3) for x in KOFF[s]) for s in KOFF})


def hand_R(side, d, n):
    """World rotation of the hand: bone Y -> d, palm normal -> n."""
    yl = Vector((0, 1, 0)); nl = NPALM[side]; nl = (nl - yl * nl.dot(yl)).normalized()
    Lb = Matrix((yl, nl, yl.cross(nl))).transposed()
    n = (n - d * n.dot(d)).normalized()
    return Matrix((d, n, d.cross(n))).transposed() @ Lb.inverted()


# ---------- body: collision trees per frame ----------
dom = dominant(body); LAB = labels(dom, RIG)
# skin thickness of every own finger bone (median distance of its skin from the bone at rest): the wrap keeps each bone that
# far from the prop. One claw thickness for all let the thumb's metacarpal (~3 cm of skin on Kusznik) bend into the stock
BONE_R = {}
if CURL:
    _co = np.array([tuple(body.matrix_world @ v.co) for v in body.data.vertices])
    for s_, fl in FING.items():
        for J, names, _ in fl:
            for b, n in enumerate(names):
                m = dom == n
                if n not in CURL or m.sum() < 5: continue
                a_, b_ = np.array(J[b]), np.array(J[b + 1]); ab = b_ - a_
                u = np.clip(((_co[m] - a_) @ ab) / max(ab @ ab, 1e-12), 0, 1)
                BONE_R[n] = float(np.median(np.linalg.norm(_co[m] - (a_ + u[:, None] * ab), axis=1)))
    print("fingers: skin radius [cm]:", {k: round(100 * v, 1) for k, v in sorted(BONE_R.items())})
tris = np.array([p.vertices[:3] for p in body.data.polygons])
T_ALL = tris[(LAB[tris] != "").all(1)].tolist()
T_CORE = tris[np.isin(LAB[tris], ("head", "torso")).all(1)].tolist()    # no clavicles: the upper arm always touches the shoulder


def trees(f):
    sc.frame_set(f); V = vertices(body, bpy.context.evaluated_depsgraph_get()).tolist()
    return BVHTree.FromPolygons(V, T_ALL, all_triangles=True), BVHTree.FromPolygons(V, T_CORE, all_triangles=True)


def hits(p, tree, r):
    loc, nor, _, d = tree.find_nearest(p, 0.3)
    if loc is None: return False
    return d < r or ((p - loc).dot(nor) < 0 and inside(tree, p))


rng = np.random.default_rng(1)
SAMP = Lc[rng.choice(len(Lc), min(260, len(Lc)), replace=False)]


def prop_hits(C4, tr):
    R = np.array(C4.to_3x3()); pts = SAMP @ R.T + np.array(C4.translation); n = 0
    for p in pts:
        p = Vector(p); loc, nor, _, d = tr[0].find_nearest(p, 0.15)
        if loc is not None and (p - loc).dot(nor) < 0 and d > 0.008 and inside(tr[0], p): n += 1
    return n


# ---------- recoil ----------
RC = MO.get("recoil")
FIRE = RC["fire_s"] * FPS if RC else None


def env(f):
    if FIRE is None: return 0.0
    t = f - FIRE
    if t < 0: return 0.0
    return t / 2 if t < 2 else math.exp(-(t - 2) / 4)


for f in all_frames:
    e = env(f)
    if e < 1e-3: continue
    sc.frame_set(f)
    for n in PROF.spine[-2:]:   # the two top spine bones lean back
        setw(n, Quaternion(Vector((1, 0, 0)), -math.radians(RC["lean_deg"] * e)).to_matrix() @ wrot(n)); keyb(n, f)

# ---------- arm motion from the AI ----------
K = {}
for f in all_frames:
    sc.frame_set(f); d = {}
    for s in ("Left", "Right"):
        d[s + "palm"] = head(BN[s]["hand"]) + wrot(BN[s]["hand"]) @ Vector((0, PALM, 0))
        d[s + "E"] = head(BN[s]["forearm"]); d[s + "S"] = head(BN[s]["upper_arm"]); d[s + "W"] = head(BN[s]["hand"])
        d[s + "Rua"] = wrot(BN[s]["upper_arm"]); d[s + "Rfa"] = wrot(BN[s]["forearm"])
    K[f] = d
zR = np.array([K[f]["Rightpalm"].z for f in all_frames])
z_lo, z_hi = np.median(zR[:8]), np.percentile(zR, 92)
W_AIM = {}
for f in all_frames:
    x = float(np.clip((K[f]["Rightpalm"].z - z_lo) / max(z_hi - z_lo, 1e-6), 0, 1)); W_AIM[f] = x * x * (3 - 2 * x)
    # walk/idle with the prop in both hands: hand height from arm swing would "aim" - the whole clip is a hold
    if MO.get("no_aim"): W_AIM[f] = 0.0
AIM = MO.get("aim", {})
# head slightly back while aiming: makes room for the stock and the right elbow
HEAD_BACK = AIM.get("head_back_deg", 0)
BUTT_PUSH = Vector(AIM.get("butt_push", tuple(FWD))).normalized()
for f in all_frames:
    if not HEAD_BACK or W_AIM[f] < 1e-3: continue
    sc.frame_set(f)
    # neck back, head forward by part of it: the head MOVES back, the gaze stays on target (tilting alone only lifted the chin)
    for n, k_ in ((PROF.bone("neck"), -1.0), (PROF.bone("head"), AIM.get("head_gaze", 0.7))):
        setw(n, Quaternion(Vector((1, 0, 0)), k_ * math.radians(HEAD_BACK * W_AIM[f])).to_matrix() @ wrot(n)); keyb(n, f)
rel_rest = {s: rest_rot(BN[s]["forearm"]).transposed() @ rest_rot(BN[s]["hand"]) for s in ("Left", "Right")}
SPLIT = GP["twist_to_forearm"]


def twist_y(Rrel):
    q = Rrel.to_quaternion(); return math.degrees(2 * math.atan2(q.y, q.w))


def grip(side, C4, roll):
    ax = [C4.to_3x3().col[i].normalized() for i in range(3)]
    g = GR[side]
    vec = lambda c: (ax[0] * c[0] + ax[1] * c[1] + ax[2] * c[2])
    qr = Quaternion(ax[0], math.radians(roll))
    n = qr @ vec(g["palm_normal"]).normalized(); d = (qr @ vec(g["direction"])).normalized()
    palm = C4.translation + ax[0] * g["x"] - n * (RS[side] + GP["clearance"])
    Rh = hand_R(side, d, n)
    if g.get("knuckles_at_edge") and side in KOFF:
        # knuckles under the middle of the stock: the first phalanx will not bend up (it would enter the stock), fingers went sideways.
        # Put the knuckles (from the hand rest pose) on the stock corner: towards the fingers s and underneath (-n), half a finger off the wall
        s = d - ax[0] * d.dot(ax[0]) - n * d.dot(n)
        if s.length > 1e-3:
            s.normalize(); R3 = C4.to_3x3().transposed(); m = stockm & (np.abs(Lc[:, 0] - g["x"]) < 0.03)
            kn = palm - d * PALM + Rh @ KOFF[side] - C4.translation
            for v in (s, -n):
                e = float((Lc[m, 1:] @ np.array((R3 @ v)[1:])).max())
                palm = palm + v * (e + 0.5 * GP["finger_thickness"] - kn.dot(v))
    return palm - d * PALM, Rh, palm


def ranges(side):
    """How far the grip may roll around the stock and the elbow around the shoulder-wrist axis (deg)."""
    return GR[side].get("roll_deg", 20), GP["elbow_deg"]


def solve_arm(side, f, C4, tr, rolls=(0,), poles=(0,), all_=False):
    """Cheapest arm setup over the grid (grip roll x elbow plane); `all_` = list of (cost, roll, elbow)."""
    k = K[f]; Sp, E0, W0 = k[side + "S"], k[side + "E"], k[side + "W"]
    la, lb = (E0 - Sp).length, (W0 - E0).length
    best = None
    for roll in rolls:
        Wt, Rh, palm = grip(side, C4, roll)
        dist = min((Wt - Sp).length, (la + lb) * 0.999); dr = (Wt - Sp).normalized()
        pole0 = (E0 - Sp) - dr * (E0 - Sp).dot(dr)
        if pole0.length < 1e-6: pole0 = -UP - dr * (-UP).dot(dr)
        pole0.normalize()
        ca = max(-1, min(1, (la * la + dist * dist - lb * lb) / (2 * la * dist)))
        for pa in poles:
            pole = Quaternion(dr, math.radians(pa)) @ pole0
            En = Sp + la * (ca * dr + math.sqrt(1 - ca * ca) * pole); Wn = Sp + dr * dist
            q1 = (E0 - Sp).rotation_difference(En - Sp); Rfa1 = q1.to_matrix() @ k[side + "Rfa"]
            Rfa2 = (Rfa1 @ Vector((0, 1, 0))).rotation_difference(Wn - En).to_matrix() @ Rfa1
            tw = twist_y(rel_rest[side].inverted() @ (Rfa2.transposed() @ Rh))
            Rfa3 = Rfa2 @ Quaternion(Vector((0, 1, 0)), math.radians(SPLIT * tw)).to_matrix()
            bend, twist = joint_angles(rest_rot(BN[side]["forearm"]), rest_rot(BN[side]["hand"]), Rfa3, Rh)   # same measure as the audit
            reach = (Wt - Sp).length - (la + lb)
            coll = sum(hits(En.lerp(Wn, t), tr[1], GP["forearm_clearance"]) for t in (0.0, 0.15, 0.4, 0.65, 0.9))
            coll += hits(Sp.lerp(En, 0.6), tr[1], GP["forearm_clearance"])   # elbow and upper arm too (the left elbow sat in the torso)
            # a clawed hand is ~0.3 m long: one centre point let it into the cheek and belly
            dn = (palm - Wt).normalized()
            coll += sum(hits(p_, tr[1], GP["hand_clearance"]) for p_ in (Wt, palm, palm + dn * 0.06, palm + dn * 0.12))
            cost = 3 * max(0, bend - 60) + 3 * max(0, abs(twist) - 45) + 40 * coll + 400 * max(0, reach)
            cost += 0.05 * abs(pa)
            et = GR[side].get("elbow_target")   # [outward, forward, up] while aiming
            if et:
                out_ = RIGHT if side == "Right" else -RIGHT
                tc = out_ * et[0] + FWD * et[1] + UP * et[2]; tc = tc - dr * tc.dot(dr)
                eo = (En - Sp) - dr * (En - Sp).dot(dr)
                if tc.length > 1e-6 and eo.length > 1e-6:
                    cost += GR[side].get("elbow_target_weight", 80) * W_AIM[f] * (1 - eo.normalized().dot(tc.normalized()))
            if all_: best = (best or []) + [(cost, roll, pa)]; continue
            if best is None or cost < best["cost"]:
                best = dict(cost=cost, roll=roll, pa=pa, q1=q1, Rfa3=Rfa3, Rh=Rh, bend=bend, twist=twist, coll=coll, reach=reach)
    return best


def pose_cost(C4, f, tr):
    c = 50 * prop_hits(C4, tr)
    for side in ("Right", "Left"):
        # a grid of 5 grips x 3 elbows instead of one setup was tried: audit score 15.5 -> 23.4, worse
        b = solve_arm(side, f, C4, tr); c += 20 * b["coll"] + 400 * max(0, b["reach"])
    return c


def shift(C4, x):
    """x = (right, up, forward, yaw in deg); yaw around the right-hand grip."""
    C2 = (Matrix.Translation(C4.translation) @ Quaternion(UP, math.radians(x[3])).to_matrix().to_4x4()
          @ Matrix.Translation(-C4.translation) @ C4)
    C2.translation += RIGHT * x[0] + UP * x[1] + FWD * x[2]
    return C2


def search(C4, f, tr):
    """Coordinate descent in both directions (an old grid only in +: the left elbow stayed in the torso)."""
    # offset with a limit and a stronger penalty: at 30/m without a limit the crossbow escaped collisions 37 cm above the head at the shot
    MX, KP = GP.get("max_offset", 0.08), GP.get("offset_penalty", 100)

    def cost(x):
        d = math.sqrt(x[0] ** 2 + x[1] ** 2 + x[2] ** 2)
        return 1e9 if d > MX + 1e-9 else pose_cost(shift(C4, x), f, tr) + KP * d + 0.3 * abs(x[3])
    x = [0.0, 0.0, 0.0, 0.0]; best = cost(x)
    if best == 0: return C4, x
    STEPS = ((0.08, 0.04, 0.02), (0.08, 0.04, 0.02), (0.08, 0.04, 0.02), (20, 10, 5))
    for _ in range(3):
        better = False
        for axis in range(4):
            for st in STEPS[axis]:
                for sg in (1, -1):
                    y = list(x); y[axis] += sg * st; c = cost(y)
                    if c < best: best, x, better = c, y, True
        if not better or best == 0: break
    return shift(C4, x), x


HOLD = MO.get("hold")


def out_of_body(p, direction, tree, clearance):
    """Moves a point along `direction` until it leaves the body volume with `clearance` to spare."""
    for _ in range(60):
        loc, nor, _, dd = tree.find_nearest(p, 0.3)
        if loc is None or ((p - loc).dot(nor) > 0 and dd > clearance): break
        p = p + direction * 0.01
    return p


def hold_pose(f):
    """Prop in both hands in front of the body, placed from the body: Kimodo hands follow human proportions
    (a hunched character: right hand 40 cm to the side, left forearm through the hip)."""
    yaw, pitch = math.radians(HOLD["yaw_deg"]), math.radians(HOLD["pitch_deg"])
    fd = FWD * math.cos(yaw) - RIGHT * math.sin(yaw)
    fd = (fd * math.cos(pitch) + UP * math.sin(pitch)).normalized()
    center = head(PROF.bone("hips")) + UP * HOLD["above_hips"]
    center = out_of_body(center, FWD, TR[f][0], HOLD["body_clearance"])
    x_mid = (GR["Right"]["x"] + GR["Left"]["x"]) / 2
    C = frame3(fd, UP).to_4x4(); C.translation = center - fd * x_mid
    return C


def base_pose(f):
    k = K[f]
    if HOLD:
        sc.frame_set(f); Ck = hold_pose(f)
    else:
        Ck = frame3((k["Leftpalm"] - k["Rightpalm"]).normalized(), UP).to_4x4(); Ck.translation = k["Rightpalm"]
    kick = math.radians(RC["kick_deg"] * env(f)) if RC else 0.0; tilt = math.radians(AIM.get("pitch_deg", 0))
    fd = (FWD * math.cos(tilt - kick) + UP * math.sin(-tilt + kick)).normalized()
    butt = k["RightS"] + Vector(AIM.get("butt_from_shoulder", (0, -0.07, -0.03)))
    # the shoulder joint lies inside the body: the butt leaves it forward (stock on the shoulder) or along `butt_push`.
    # A stock under the armpit (Kusznik on amts, author 2026-11-19) pushed forward ended 10 cm in front of the chest.
    # Pushed sideways it leaves the torso alone: the upper arm closes over it (out of the whole body it went through the arm
    # and stopped 13 cm outside the shoulder joint)
    butt = out_of_body(butt, BUTT_PUSH, TR[f][1] if "butt_push" in AIM else TR[f][0], 0.01)
    Ca = frame3(fd, UP).to_4x4(); Ca.translation = butt - fd * BUTT
    w = W_AIM[f]
    C = Ck.to_quaternion().slerp(Ca.to_quaternion(), w).to_matrix().to_4x4()
    C.translation = Ck.translation.lerp(Ca.translation, w)
    # forward arc between hold and aim: a straight line went through the chest
    C.translation += FWD * AIM.get("transition_arc", 0.0) * 4 * w * (1 - w)
    return C, w


def smooth(OFF):
    if A.frames: return {f: list(OFF[f]) for f in frames}
    SM = {}
    for f in frames:
        acc, ws = np.zeros(4), 0
        for g in range(f - 3, f + 4):
            if g in OFF: ww = 1 - abs(g - f) / 4; acc += np.array(OFF[g]) * ww; ws += ww
        SM[f] = list(acc / ws)
    return SM


PREV_F = {}   # bend angle of every finger bone from the previous frame


def wrap_fingers(C4):
    Ci = C4.inverted(); g = GP["finger_thickness"]   # joints are the finger axis; the claw skin is that much further out

    def sd(p, tree=PBVH):
        """Signed distance from the prop surface (< 0 inside, by the normal of the nearest face)."""
        q = Ci @ p; loc, nrm, _, d = tree.find_nearest(q)
        if loc is None: return 1.0
        return d if (q - loc).dot(nrm) >= 0 else -d

    def dists(ps, own):
        """Distances for the wrap cost: (target, collision). Own chains wrap onto the stock alone (PBVH_STOCK) and still
        keep out of the whole prop (stock-only collision let the fingers into the mount: fingers_in_prop 1.8 -> 2.0 cm)."""
        full = [sd(p_) for p_ in ps]
        return ([sd(p_, PBVH_STOCK) for p_ in ps] if own else full), full
    for side, fl in FING.items():
        Hn = wmat(BN[side]["hand"]); Hn.normalize(); T = Hn @ hand_rest[side].normalized().inverted()
        npw = (wrot(BN[side]["hand"]) @ NPALM[side]).normalized()
        JW = [[T @ j for j in J] for J, _, _ in fl]
        # own thumb: cost of its tip direction off the stock axis, for each of its bones (only the metacarpal: the other two
        # bent on towards the palm normal looking for a surface they could not reach and stood up as a hook)
        # 0.05 was tuned while Kusznik's stock had a hole by the right hand (the thumb lay in it); with the hole capped the
        # thick thumb base collided lying along the stock and the thumb stood up as a hook again: 0.2 lays it along (0.8 -> 0.49)
        stock = C4.to_3x3().col[0].normalized(); ALONG = GP.get("thumb_along_stock", 0.2)
        # a finger's change from the previous frame costs, except in a quick try (--frames): its frames are not neighbours
        # (key poses 0,44: the left middle finger kept frame 0's angle at 44, tip 1.3 -> 3.1 cm off the stock)
        FCP = 0 if A.frames else GP.get("finger_change_penalty", 0.0015)
        # own fingers close together: each joint's angle costs its distance from the same joint of the finger before it
        # (index -> pinky). Solved alone, Kusznik's index and middle arched far round the stock apart from ring and pinky
        NEXT = {}
        own_f = [k for k, (_, names, thumb) in enumerate(fl) if not thumb and names[0] in SPREAD]
        md = sum(((JW[k][1] - JW[k][0]).normalized() for k in own_f), Vector())
        for (J, names, thumb), Jw in zip(fl, JW):
            b0 = 0; own_c = names[0] in CURL
            if names[0] in SPREAD and not thumb and md.length > 1e-6:
                # own fingers side by side: each first bone turns in the palm plane onto the fingers' mean direction.
                # Spread as at rest, the long index/middle of Kusznik wrapped far over the stock apart from ring/pinky
                sp = (wrot(names[0]) @ SPREAD[names[0]]).normalized(); d0 = Jw[1] - Jw[0]
                u, v = d0 - sp * d0.dot(sp), md - sp * md.dot(sp)
                if u.length > 1e-6 and v.length > 1e-6:
                    q = Quaternion(sp, math.atan2(u.normalized().cross(v.normalized()).dot(sp), u.normalized().dot(v.normalized())))
                    for j in range(1, 4): Jw[j] = Jw[0] + q @ (Jw[j] - Jw[0])
                    setw(names[0], q.to_matrix() @ wrot(names[0]), h=Jw[0], loc=True)
            if names[0] in SPREAD and thumb:
                # own thumb: turns in the palm plane (abduction) and bends at its metacarpal together, to lie along the
                # stock's side with its tip forward or back. Bending alone carried it over the top of the stock as a hook
                sp = (wrot(names[0]) @ SPREAD[names[0]]).normalized(); fx = (wrot(names[0]) @ CURL[names[0]]).normalized()
                best = (1e9, None, 0, 0)
                for ab in range(-60, 61, 10):
                    qs = Quaternion(sp, math.radians(ab))
                    for a in range(-45, 46, 5):
                        q = Quaternion(qs @ fx, math.radians(a)) @ qs
                        pts = [Jw[0] + q @ (Jw[j] - Jw[0]) for j in (1, 2, 3)]
                        mids = [Jw[0].lerp(pts[0], 0.5), pts[0].lerp(pts[1], 0.5), pts[1].lerp(pts[2], 0.5)]
                        gl = [max(g, BONE_R.get(n, g)) for n in names] + [max(g, BONE_R.get(n, g)) for n in names]
                        d_, f_ = dists(pts + mids, own_c)
                        c_ = abs(d_[0] - (gl[0] + 0.005)) + sum(10 + 100 * (gg - x) for x, gg in zip(f_, gl) if x < gg)
                        c_ += ALONG * (1 - abs((pts[2] - Jw[0]).normalized().dot(stock)))
                        c_ += FCP * (abs(a - PREV_F.get(names[0], a))
                                                                          + abs(ab - PREV_F.get(names[0] + "@spread", ab)))
                        if c_ < best[0]: best = (c_, q, ab, a)
                _, q, PREV_F[names[0] + "@spread"], PREV_F[names[0]] = best
                for j in range(1, 4): Jw[j] = Jw[0] + q @ (Jw[j] - Jw[0])
                setw(names[0], q.to_matrix() @ wrot(names[0]), h=Jw[0], loc=True); b0 = 1
            for b in range(b0, 3):
                pivot = Jw[b]
                axis = wrot(names[b]) @ CURL[names[b]] if names[b] in CURL else (Jw[b + 1] - Jw[b]).normalized().cross(npw)
                if axis.length < 1e-6: continue
                axis.normalize(); best = (1e9, 0)
                # the thumb opposes the fingers: it may bend both ways (it wrapped away from the stock). The own skeleton's bones
                # bend about their own axis, so its thumb wraps one way too, and its first bone is the metacarpal: 0..45 deg
                # (-90..95 zig-zagged the thumb: -50 / +75 / -70 deg; -45..45 put its base 3.2 cm into the stock, 0..45 2.3 cm)
                own = names[b] in CURL; lo, hi = (-90, 95) if thumb else (0, 95)
                if own: lo, hi = (0, 45) if thumb and b == 0 else (0, 95)

                def chain(a, curl_rest):
                    """Joints after bone b turned by a; with curl_rest the bones after it bend by a too (about their own axes)."""
                    P_ = list(Jw); acc = Quaternion()
                    for j in range(b, 3 if curl_rest else b + 1):
                        ax = axis if j == b else (acc @ (wrot(names[j]) @ CURL[names[j]])).normalized()
                        qq = Quaternion(ax, math.radians(a)); acc = qq @ acc
                        P_ = P_[:j + 1] + [P_[j] + qq @ (P_[k] - P_[j]) for k in range(j + 1, 4)]
                    return P_[b + 1:]

                def search(curl_rest):
                    best_ = (1e9, 0)
                    for a in range(lo, hi + 1, 5):
                        pts = chain(a, curl_rest)
                        mids = [pivot.lerp(pts[0], 0.5)] + [pts[i].lerp(pts[i + 1], 0.5) for i in range(len(pts) - 1)]
                        d_, f_ = dists(pts + mids, own_c)
                        gl = [max(g, BONE_R.get(names[min(b + j, 2)], g)) for j in range(len(pts))] + [
                            max(g, BONE_R.get(names[b + k], g)) for k in range(len(mids))]
                        c_ = abs(d_[0] - (gl[0] + 0.005)) + sum(10 + 100 * (gg - x) for x, gg in zip(f_, gl) if x < gg)
                        c_ += FCP * abs(a - PREV_F.get(names[b], a))   # 0.0015/deg ~ 1.5 mm per 1 deg
                        if own and thumb: c_ += ALONG * (1 - abs((pts[-1] - Jw[0]).normalized().dot(stock)))
                        if own and not thumb and b in NEXT: c_ += GP.get("finger_together_penalty", 0.001) * abs(a - NEXT[b])
                        if c_ < best_[0]: best_ = (c_, a)
                    return best_
                best = search(False)
                # an own finger bent rigidly swings its straight rest into the stock, so it stopped half bent (Kusznik's
                # right middle finger stood up, tip 5-9 cm off the stock). Also try the rest of the finger curling with
                # it, as a real finger closes round the stock, and keep whichever lands better (middle.2.R 35 deg ->
                # 95 deg, tip gap 8.7 -> 2.5 cm)
                if own and not thumb and b < 2:
                    curled = search(True)
                    if curled[0] < min(best[0], 10): best = curled
                if own and not thumb: NEXT[b] = best[1]
                PREV_F[names[b]] = best[1]; q = Quaternion(axis, math.radians(best[1]))
                for j in range(b + 1, 4): Jw[j] = pivot + q @ (Jw[j] - pivot)
                setw(names[b], q.to_matrix() @ wrot(names[b]), h=Jw[b], loc=True)


def path(side, CP, TR):
    """Grip roll and elbow for the whole clip at once (Viterbi): a frame-by-frame choice jumped between nearly equal
    setups (hand 60 deg, elbow 15 cm, fingers 95 deg between neighbouring frames)."""
    R_, L_ = ranges(side)
    rolls, poles = list(range(-R_, R_ + 1, 10)), list(range(-L_, L_ + 1, 15))
    st = [(r, p) for r in rolls for p in poles]; ix = {s: i for i, s in enumerate(st)}
    states = np.array(st, float)
    # quick try: frames are not neighbours, so a change between them costs nothing
    trans = (0 if A.frames else GP.get("change_penalty", 0.02)) * (
        (states[:, None, 0] - states[None, :, 0]) ** 2 + (states[:, None, 1] - states[None, :, 1]) ** 2)
    acc = None; back = []
    for f in frames:
        u = np.full(len(st), 1e9)
        for c, r, p in solve_arm(side, f, CP[f], TR[f], rolls, poles, all_=True): u[ix[(r, p)]] = c
        if acc is None: acc = u; continue
        m = acc[:, None] + trans; b = m.argmin(0); back.append(b); acc = m[b, np.arange(len(st))] + u
    k = int(acc.argmin()); pth = [k]
    for b in reversed(back): k = int(b[k]); pth.append(k)
    pth = [st[i] for i in reversed(pth)]
    if A.frames: return dict(zip(frames, pth))
    sm = {}
    for i, f in enumerate(frames):
        w = [(1 - abs(j - i) / 4, pth[j]) for j in range(max(0, i - 3), min(len(frames), i + 4))]
        sm[f] = tuple(sum(ww * v[q] for ww, v in w) / sum(ww for ww, _ in w) for q in (0, 1))
    return sm


def place(f, C4, prevs, tr):
    sc.frame_set(f)
    for b_ in arm.pose.bones:
        if b_.name.startswith(FINGER_PREFIX) or b_.name in FING_NAMES: b_.rotation_quaternion = (1, 0, 0, 0); b_.location = (0, 0, 0)
    bpy.context.view_layer.update()
    set_prop(C4, f); out = {}
    for side in ("Right", "Left"):
        r, p = prevs[side][f]; b = solve_arm(side, f, C4, tr, [r], [p])
        setw(BN[side]["upper_arm"], b["q1"].to_matrix() @ K[f][side + "Rua"]); setw(BN[side]["forearm"], b["Rfa3"]); setw(BN[side]["hand"], b["Rh"])
        for n in ("upper_arm", "forearm", "hand"): keyb(BN[side][n], f)
        out[side] = dict(roll=b["roll"], elbow=b["pa"], bend=round(b["bend"], 1), twist=round(b["twist"], 1), collisions=b["coll"])
    wrap_fingers(C4)
    for chains in FING.values():
        for _, names, _ in chains:
            for n in names: keyb(n, f, loc=True)
    return out


# pass 1: body volume with AI arms; later passes: volume after IK, offset counted from the base pose (not accumulated)
TIME = {}


def stopwatch(what, t0):
    TIME[what] = TIME.get(what, 0.0) + time.perf_counter() - t0; return time.perf_counter()


t0 = time.perf_counter()
TR = {f: trees(f) for f in frames}; t0 = stopwatch("trees", t0)
BASE = {f: base_pose(f) for f in frames}; t0 = stopwatch("base pose", t0)
OFF = {f: [0.0, 0.0, 0.0, 0.0] for f in frames}
todo = frames
for it in range(GP.get("passes", 4)):
    for f in todo:
        OFF[f] = search(BASE[f][0], f, TR[f])[1]
    t0 = stopwatch("search", t0)
    SM = smooth(OFF)
    CP = {f: shift(BASE[f][0], SM[f]) for f in frames}
    prevs = {s: path(s, CP, TR) for s in ("Left", "Right")}; PREV_F.clear(); t0 = stopwatch("path", t0)
    WR = {f: place(f, CP[f], prevs, TR[f]) for f in frames}; t0 = stopwatch("place (IK + fingers)", t0)
    TR = {f: trees(f) for f in frames}; t0 = stopwatch("trees", t0)
    todo = [f for f in frames if prop_hits(CP[f], TR[f]) or any(WR[f][s]["collisions"] for s in WR[f])]; t0 = stopwatch("check", t0)
    print("pass", it + 1, "frames with collision:", len(todo), todo[:25])
    if not todo: break
print("time [s]:", ", ".join("%s %.1f" % kv for kv in TIME.items()))
# a solution stuck at the end of its range is limited by the range (or the grip itself), not the cost: tune the range/grip, not weights
for s_ in GR:
    R_, L_ = ranges(s_)
    for what, i, lim in (("grip roll", 0, R_), ("elbow", 1, L_)):
        u = sum(abs(prevs[s_][f][i]) >= lim - 0.5 for f in frames) / len(frames)
        if u >= 0.25: print("LIMIT %s: %s at the end of its range +-%d deg in %.0f%% of frames" % (SIDE_NAME[s_], what, lim, 100 * u))
MX_ = GP.get("max_offset", 0.08)
offs = {f: math.sqrt(sum(v * v for v in SM[f][:3])) for f in frames}; f_ = max(offs, key=offs.get)
# the audit only sees penetration; whether the prop is where it was asked to be, this line says (a crossbow ended 37 cm above the head)
print("PROP POSE: offset from requested max %.0f cm (fr. %d), mean %.0f cm" % (100 * offs[f_], f_, 100 * sum(offs.values()) / len(offs)))
u = sum(v >= MX_ - 0.005 for v in offs.values()) / len(frames)
if u >= 0.1: print("LIMIT prop: offset from the requested pose at the %.0f cm limit in %.0f%% of frames" % (100 * MX_, 100 * u))
for f in frames: WR[f]["offset"] = [round(v, 4) for v in SM[f]]

# finger smoothing in time: frame-by-frame wrapping jumped (95 deg between frames); collisions are checked by the audit.
# Arms are NOT smoothed: +-2 frames broke the grip (hand in head 3.1 -> 7.2 cm, wrist twist 77 deg, score 10.4 -> 21.7)
FC = act.fcurves if hasattr(act, "fcurves") else [c for l in act.layers for st in l.strips for b in st.channelbags for c in b.fcurves]


def smooth_curves(match, window):
    groups = {}
    for fc in FC:
        if match(fc.data_path): groups.setdefault(fc.data_path, {})[fc.array_index] = fc
    for dp, ch in groups.items():
        n = len(ch); kp = [ch[i].keyframe_points for i in range(n)]
        if len({len(k) for k in kp}) > 1: continue
        V = np.array([[kp[i][j].co[1] for i in range(n)] for j in range(len(kp[0]))])
        if dp.endswith("rotation_quaternion"):
            for j in range(1, len(V)):
                if V[j] @ V[j - 1] < 0: V[j] = -V[j]
        W_ = np.zeros_like(V)
        for j in range(len(V)):
            ws = [(1 - abs(d) / (window + 1), V[j + d]) for d in range(-window, window + 1) if 0 <= j + d < len(V)]
            W_[j] = sum(w * v for w, v in ws) / sum(w for w, _ in ws)
        if dp.endswith("rotation_quaternion"): W_ /= np.linalg.norm(W_, axis=1, keepdims=True)
        for i in range(n):
            for j in range(len(V)): kp[i][j].co[1] = W_[j, i]; kp[i][j].handle_left_type = kp[i][j].handle_right_type = "AUTO_CLAMPED"
            ch[i].update()
    return len(groups)


if not A.frames: print("smoothed: fingers", smooth_curves(lambda d: d.startswith('pose.bones["' + FINGER_PREFIX) or d.split('"')[1] in FING_NAMES, 3))

json.dump({str(f): v for f, v in WR.items()}, open(A.out.replace(".glb", "_arms.json"), "w"), indent=0)
bpy.ops.export_scene.gltf(filepath=A.out, export_format="GLB", export_animations=True)
print("OK", A.out)
