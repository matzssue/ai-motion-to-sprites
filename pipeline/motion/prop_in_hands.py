"""Prop (cut out by prepare_rig) in both hands on an AI motion: a prop pose searched without body collisions,
both arms by analytic IK to the grip from the motion file (grip roll and elbow chosen for the wrist and for collisions),
fingers wrapped around the stock, torso recoil. The result is checked by motion_audit.py - never shown without it.
blender -b --python pipeline/motion/prop_in_hands.py -- --glb merged.glb --rig-data rig_ai_data.json --motion <motion>.json --out out.glb
    [--frames 10,45,56]  quick grip try: only these frames, best grip for each on its own (no path or smoothing in time)
Blender's IK does not work on rigs from GLB (bone lengths are meaningless), hence IK from bone heads."""
import bpy, sys, os, math, json, argparse, time
import numpy as np
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from collisions import dominant, labels, vertices, inside, joint_angles, FINGER_PREFIX

ap = argparse.ArgumentParser(description="Put the prop in both hands: prop pose, two-arm IK, finger wrap, recoil.")
ap.add_argument("--glb", required=True); ap.add_argument("--rig-data", required=True)
ap.add_argument("--motion", required=True); ap.add_argument("--out", required=True); ap.add_argument("--frames", default=None)
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
P = next((b.name.split(":")[0] + ":" for b in arm.data.bones if ":" in b.name), "")
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
AXES = {"forward": (1, 0, 0), "back": (-1, 0, 0), "left": (0, 1, 0), "right": (0, -1, 0), "up": (0, 0, 1), "down": (0, 0, -1)}
# side of the prop the hand is on -> where its palm faces
PALM_SIDE = {"from below": (0, 0, 1), "from above": (0, 0, -1), "from the right": (0, 1, 0), "from the left": (0, -1, 0),
             "from behind": (1, 0, 0), "from the front": (-1, 0, 0)}
SIDE_NAME = {"Right": "right", "Left": "left"}


def nearest(tab, v):
    v = Vector(v).normalized(); return max(tab, key=lambda k: v.dot(Vector(tab[k])))


def grip_from_words(g):
    """`palm`: "from below", `fingers`: "left", `fingers_tilt`: ["forward", 18] -> palm_normal, direction (when given in words)."""
    if "palm" in g: g["palm_normal"] = list(PALM_SIDE[g["palm"]])
    if "fingers" in g:
        d = Vector(AXES[g["fingers"]]); toward, deg = g.get("fingers_tilt", ("forward", 0))
        g["direction"] = list(d * math.cos(math.radians(deg)) + Vector(AXES[toward]) * math.sin(math.radians(deg)))
    return g


def grip_in_words(g):
    d = Vector(g["direction"]).normalized(); a = nearest(AXES, d); rest = d - Vector(AXES[a]) * d.dot(Vector(AXES[a]))
    tilt = math.degrees(math.asin(min(1.0, rest.length)))
    return "palm %s, fingers %s%s, %.0f cm in front of the butt" % (
        nearest(PALM_SIDE, g["palm_normal"]), a, " and %.0f deg %s" % (tilt, nearest(AXES, rest)) if tilt > 3 else "", 100 * (g["x"] - BUTT))


GR = {"Right": grip_from_words(GP["right"]), "Left": grip_from_words(GP["left"])}
for s_ in GR: print("grip %s: %s" % (SIDE_NAME[s_], grip_in_words(GR[s_])))
RS = {s: r_at(GR[s]["x"]) for s in GR}
print("stock: butt %.3f, radius at grips R %.3f / L %.3f" % (BUTT, RS["Right"], RS["Left"]))
# fingers wrap around the real surface: a stock is not a cylinder (left hand: 7 cm down, 3-5 cm to the sides);
# a cylinder radius kept the left claws 5-16 cm from the stock
PBVH = BVHTree.FromPolygons([Vector(v) for v in Lc], [tuple(q.vertices) for q in prop.data.polygons])


def set_prop(C4, f):
    pb(PN).matrix = AWi @ (C4 @ CR_IN_BONE.inverted())
    bpy.context.view_layer.update(); keyb(PN, f, loc=True)


# ---------- hands and fingers from the rig ----------
NPALM = {s: Vector(RD["palm"][s]["local_normal"]) for s in RD["palm"]}
hand_rest = {s: AW @ bone(s + "Hand").matrix_local for s in ("Left", "Right")}
FING = {}
for s, chains in RD["fingers"].items():
    FING[s] = [([AW @ bone(n).head_local for n in ch] + [AW @ bone(ch[-1]).tail_local], ch, k in RD["thumbs"].get(s, []))
               for k, ch in enumerate(chains)]


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
dom = dominant(body); LAB = labels(dom)
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
    for n in ("Spine1", "Spine2"):
        setw(n, Quaternion(Vector((1, 0, 0)), -math.radians(RC["lean_deg"] * e)).to_matrix() @ wrot(n)); keyb(n, f)

# ---------- arm motion from the AI ----------
K = {}
for f in all_frames:
    sc.frame_set(f); d = {}
    for s in ("Left", "Right"):
        d[s + "palm"] = head(s + "Hand") + wrot(s + "Hand") @ Vector((0, PALM, 0))
        d[s + "E"] = head(s + "ForeArm"); d[s + "S"] = head(s + "Arm"); d[s + "W"] = head(s + "Hand")
        d[s + "Rua"] = wrot(s + "Arm"); d[s + "Rfa"] = wrot(s + "ForeArm")
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
for f in all_frames:
    if not HEAD_BACK or W_AIM[f] < 1e-3: continue
    sc.frame_set(f)
    # neck back, head forward by part of it: the head MOVES back, the gaze stays on target (tilting alone only lifted the chin)
    for n, k_ in (("Neck", -1.0), ("Head", AIM.get("head_gaze", 0.7))):
        setw(n, Quaternion(Vector((1, 0, 0)), k_ * math.radians(HEAD_BACK * W_AIM[f])).to_matrix() @ wrot(n)); keyb(n, f)
rel_rest = {s: rest_rot(s + "ForeArm").transposed() @ rest_rot(s + "Hand") for s in ("Left", "Right")}
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
    if g.get("knuckles_at_edge"):
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
            bend, twist = joint_angles(rest_rot(side + "ForeArm"), rest_rot(side + "Hand"), Rfa3, Rh)   # same measure as the audit
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
    center = head("Hips") + UP * HOLD["above_hips"]
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
    butt = out_of_body(butt, FWD, TR[f][0], 0.01)   # the shoulder joint lies inside the body
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

    def sd(p):
        """Signed distance from the prop surface (< 0 inside, by the normal of the nearest face)."""
        q = Ci @ p; loc, nrm, _, d = PBVH.find_nearest(q)
        if loc is None: return 1.0
        return d if (q - loc).dot(nrm) >= 0 else -d
    for side, fl in FING.items():
        Hn = wmat(side + "Hand"); Hn.normalize(); T = Hn @ hand_rest[side].normalized().inverted()
        npw = (wrot(side + "Hand") @ NPALM[side]).normalized()
        for J, names, thumb in fl:
            Jw = [T @ j for j in J]
            for b in range(3):
                pivot = Jw[b]; axis = (Jw[b + 1] - Jw[b]).normalized().cross(npw)
                if axis.length < 1e-6: continue
                axis.normalize(); best = (1e9, 0)
                # the thumb opposes the fingers: it may bend both ways (it wrapped away from the stock)
                for a in range(-90 if thumb else 0, 96, 5):
                    q = Quaternion(axis, math.radians(a))
                    pts = [pivot + q @ (Jw[j] - pivot) for j in range(b + 1, 4)]
                    mids = [pivot.lerp(pts[0], 0.5)] + [pts[i].lerp(pts[i + 1], 0.5) for i in range(len(pts) - 1)]
                    d_ = [sd(p) for p in pts + mids]
                    c_ = abs(d_[0] - (g + 0.005)) + sum(10 + 100 * (g - x) for x in d_ if x < g)
                    c_ += GP.get("finger_change_penalty", 0.0015) * abs(a - PREV_F.get(names[b], a))   # 0.0015/deg ~ 1.5 mm per 1 deg
                    if c_ < best[0]: best = (c_, a)
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
        if b_.name.startswith(FINGER_PREFIX): b_.rotation_quaternion = (1, 0, 0, 0); b_.location = (0, 0, 0)
    bpy.context.view_layer.update()
    set_prop(C4, f); out = {}
    for side in ("Right", "Left"):
        r, p = prevs[side][f]; b = solve_arm(side, f, C4, tr, [r], [p])
        setw(side + "Arm", b["q1"].to_matrix() @ K[f][side + "Rua"]); setw(side + "ForeArm", b["Rfa3"]); setw(side + "Hand", b["Rh"])
        for n in ("Arm", "ForeArm", "Hand"): keyb(side + n, f)
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


if not A.frames: print("smoothed: fingers", smooth_curves(lambda d: d.startswith('pose.bones["' + FINGER_PREFIX), 3))

json.dump({str(f): v for f, v in WR.items()}, open(A.out.replace(".glb", "_arms.json"), "w"), indent=0)
bpy.ops.export_scene.gltf(filepath=A.out, export_format="GLB", export_animations=True)
print("OK", A.out)
