"""Prop (cut out by prepare_rig) in both hands on an AI motion: a prop pose searched without body collisions,
both arms by analytic IK to the grip from the motion file (grip roll and elbow chosen for the wrist and for collisions),
fingers wrapped around the stock, torso recoil. The result is checked by motion_audit.py - never shown without it.
blender -b --python pipeline/motion/prop_in_hands.py -- --glb merged.glb --rig-data rig_ai_data.json --motion <motion>.json --out out.glb
    [--skeleton mixamo|profile.json]   bones by role; a skeleton without fingers: no finger wrap (reported as skipped)
    [--frames 10,45,56]  quick grip try: only these frames, best grip for each on its own (no path or smoothing in time)
    [--keep-prop]  a key pose set by hand: the prop and the body stay as the GLB has them, only both arms (IK to the
                   grip) and the fingers are fitted to the prop
    [--poses approved.glb]  the approved key poses: the prop's place against the body on the motion file's key frames is
                   the target on every frame (hold poses follow the hips, aim poses the chest at the butt-side shoulder)
Blender's IK does not work on rigs from GLB (bone lengths are meaningless), hence IK from bone heads."""
import bpy, sys, os, math, json, argparse, time, hashlib
import numpy as np
from mathutils import Matrix, Vector, Quaternion
from mathutils.bvhtree import BVHTree
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
from collisions import dominant, labels, vertices, inside, joint_angles, rig_of, FINGER_PREFIX
from collisions import labels_all, prop_in_body, depths, stock_end, pocket_gap, limb_radius, POCKET_REST, POCKET_SPAN, POCKET_ARM
from audit_metrics import METRICS, REF_HEIGHT, height
from grip_words import grip_from_words, grip_in_words
from descent import descend as descend_steps, faces_on
from prop_path import aim_window, aim_weight, nearest, carry, smooth_runs, best_path

ap = argparse.ArgumentParser(description="Put the prop in both hands: prop pose, two-arm IK, finger wrap, recoil.")
ap.add_argument("--glb", required=True); ap.add_argument("--rig-data", required=True)
ap.add_argument("--motion", required=True); ap.add_argument("--out", required=True); ap.add_argument("--frames", default=None)
ap.add_argument("--skeleton", default=None, help="skeleton profile: built-in name or JSON path (default mixamo)")
ap.add_argument("--keep-prop", action="store_true", help="keep the prop and body of the GLB, fit only the arms and fingers")
ap.add_argument("--poses", default=None, help="GLB of the approved key poses: where it holds the prop on the motion file's key frames is the target")
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
HELD = {}   # frame -> sides whose key-pose hand already holds the prop (--keep-prop)
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
_LA = labels_all(dom, RIG); _SV = np.array([RIG.bone_side(d) for d in dom])
T_ARM = {s_: tris[np.isin(_LA[tris], ("upper_arms", "forearms")).all(1) & (_SV[tris] == s_[0]).all(1)].tolist() for s_ in ("Left", "Right")}


# the skin of every upper arm and forearm in its bone's frame: the arm solver moves it rigidly with a candidate setup.
# Only skin that follows the bone (weight >= ARM_CORE_W): the armpit fold, half on the ribs, swung rigidly with an open
# arm read 11 cm of stock inside the arm; the fold is left to the real skin in skin_cost
ARM_CORE_W = 0.9
ARM_COLL = bool(CURL) or "butt_push" in MO.get("aim", {})


def bone_weight(name):
    gi = body.vertex_groups.get(name)
    w = np.zeros(len(body.data.vertices))
    if gi is None: return w
    for v in body.data.vertices:
        for g in v.groups:
            if g.group == gi.index: w[v.index] = g.weight
    return w


T_SEG = {(s_, sg): tris[(bone_weight(BN[s_][sg]) >= ARM_CORE_W)[tris].all(1)].tolist() if ARM_COLL else []
         for s_ in ("Left", "Right") for sg in ("upper_arm", "forearm")}


def tree_on(V, sub):
    """BVH of the faces `sub` = faces_on(T) on the vertices V: the tree is handed only the vertices it is built from."""
    return BVHTree.FromPolygons(V[sub[0]].tolist(), sub[1], all_triangles=True)


F_ALL, F_CORE = faces_on(T_ALL), faces_on(T_CORE)
F_ARM = {s_: faces_on(T) for s_, T in T_ARM.items()}; F_SEG = {k: faces_on(T) for k, T in T_SEG.items() if T}
ARM_REACH = 0.12   # a prop point further than this from a limb's skin is not in it


def arm_local(V):
    """{(side, bone): (BVH of its skin in the bone's frame, axial range [m], box of the skin grown by ARM_REACH)} on the
    current pose."""
    out = {}
    for (s_, sg), (I, T) in F_SEG.items():
        # world -> bone over all vertices, then the limb's: the product of a part of the array may round differently
        R = np.array(wrot(BN[s_][sg])); h = np.array(head(BN[s_][sg])); L = ((V - h) @ R)[I]
        lo, hi = L.min(0), L.max(0)
        out[(s_, sg)] = (BVHTree.FromPolygons(L.tolist(), T, all_triangles=True), float(lo[1]) + 0.01, float(hi[1]) - 0.01,
                         lo - (ARM_REACH + 1e-4), hi + (ARM_REACH + 1e-4))
    return out


SIG = {}   # frame -> fingerprint of the body the trees were built on (see signature)


def signature(V):
    """Fingerprint of the current frame as the search sees it: the deformed skin and every bone (pose and own channels).
    Two passes with the same fingerprint give search() the same input, so the same answer."""
    h = hashlib.blake2b(V.tobytes(), digest_size=16)
    for b in arm.pose.bones:
        h.update(np.array(b.matrix, np.float32).tobytes()); h.update(np.array(b.matrix_basis, np.float32).tobytes())
    return h.digest()


def trees(f):
    sc.frame_set(f); V = vertices(body, bpy.context.evaluated_depsgraph_get()); SIG[f] = signature(V)
    return (tree_on(V, F_ALL), tree_on(V, F_CORE),
            tree_on(V, F_ARM[BUTT_SIDE]) if UNDER else None,   # the arm round the pocket
            arm_local(V) if ARM_COLL else None)


def arm_depth(loc, R, h, pts):
    """Deepest of `pts` inside a limb skin moved rigidly to rotation R and head h (m, 0 = none). Only points within the
    skin's own axial range count: the tube is open at both ends and a point past its end looked inside."""
    if loc is None or not len(pts): return 0.0
    tree, y0, y1, lo, hi = loc; L = (pts - np.array(h)) @ np.array(R); dmax = 0.0
    # points outside the skin's grown box have nothing within ARM_REACH: asking the tree about them returned nothing
    for q in L[(L[:, 1] > y0) & (L[:, 1] < y1) & (L > lo).all(1) & (L < hi).all(1)].tolist():
        hit, nor, _, d = tree.find_nearest(q, ARM_REACH)
        if hit is not None and d > dmax and (Vector(q) - hit).dot(nor) < 0: dmax = d
    return dmax


def hits(p, tree, r):
    loc, nor, _, d = tree.find_nearest(p, 0.3)
    if loc is None: return False
    return d < r or ((p - loc).dot(nor) < 0 and inside(tree, p))


rng = np.random.default_rng(1)
SAMP = Lc[rng.choice(len(Lc), min(260, len(Lc)), replace=False)]


# the arms are not in the collision trees (they move with the prop): a stock butt under the armpit went through the right
# forearm and upper arm unseen (author, Kusznik: "the weapon goes through the forearm"). On the own skeleton and with a
# stock under the arm the arm solver keeps the prop out of the real upper arm and forearm skin, moved rigidly with each
# candidate (capsules round the bones saw 1 cm where the audit found 7 cm by the armpit); the forearm's last WRIST_FREE
# next to the gripping hand is left out, the stock lies in that palm. The Mixamo path keeps its tuned setup.
WRIST_FREE = 0.08
REACH_SLACK = 0.04   # own skeleton: share of the arm's length a grip should stay short of a straight arm


def prop_pts(C4): return SAMP @ np.array(C4.to_3x3()).T + np.array(C4.translation)


# the audit's prop_in_body on the solved pose (same skin, regions and grip zone): on the own skeleton and under
# the armpit a frame over its limit goes into the next pass, so a pose the audit fails is not handed on silently
LAB_ALL = labels_all(dom, RIG); SIDE_V = np.array([RIG.bone_side(d) for d in dom])
# limits scale with the audit's height: the unposed mesh is the rig's rest pose
HT = height([(body.matrix_world @ v.co).z for v in body.data.vertices])
BODY_LIM = METRICS["prop_in_body"][0] * HT / REF_HEIGHT
BODYD = {}


def body_check(f, C4):
    """(deepest prop point in the skin outside the grip zone and rest contact [m], region) on the posed frame."""
    sc.frame_set(f); BODYD[f] = body_depth(C4, pinned(f))
    return BODYD[f]


# the audit's hands/forearms in the head and torso, with its limits: the left forearm across a hunched chest went 4.5 cm
# into the jaw while the solver's few test points saw one collision
_REG_BODY = LAB[np.array(T_ALL)[:, 0]]
_I_LIMB = {w_: np.where(LAB_ALL == w_)[0][::2] for w_ in ("hands", "forearms")}
LIMB_LIM = {(w_, r_): METRICS["%s_in_%s" % (w_, r_)][0] * HT / REF_HEIGHT for w_ in ("hands", "forearms") for r_ in ("head", "torso")}


# the audit's armpit pocket test (collisions.pocket_gap) on the solved pose: rear end and stock radius in the prop's frame
(_END_L, STOCK_RM) = stock_end(np.asarray(Lc))
_co0 = np.array([tuple(body.matrix_world @ v.co) for v in body.data.vertices])
UA_R = {s_: limb_radius(_co0, dom == BN[s_]["upper_arm"], np.array(AW @ bone(BN[s_]["upper_arm"]).head_local),
                        np.array(AW @ bone(BN[s_]["forearm"]).head_local)) for s_ in ("Left", "Right")}
UA_V = {s_: dom == BN[s_]["upper_arm"] for s_ in ("Left", "Right")}
POCKET_LIM = METRICS["rest_gap"][0] or 0.02


def limbs_excess(co, C4=None):
    """Sum of hands/forearms depth in the head and torso past the audit's limits [m]; with C4 also the rear end's
    distance from the armpit pocket (as the audit's rest_gap)."""
    T = tree_on(co, F_ALL); e = 0.0
    for w_, I in _I_LIMB.items():
        for r_, (d, _, _) in depths(T, _REG_BODY, co[I]).items():
            if (w_, r_) in LIMB_LIM: e += max(0.0, d - 0.8 * LIMB_LIM[(w_, r_)])
    if C4 is None: return e, 0.0
    S = {s_: np.array(head(BN[s_]["upper_arm"])) for s_ in ("Left", "Right")}
    b, front, sd = rear_end(C4, S)
    up = np.array(head(PROF.spine[-1]) - head(PROF.spine[0])); up /= np.linalg.norm(up)
    rt = S["Right"] - S["Left"]; rt -= up * (rt @ up); rt /= np.linalg.norm(rt)
    return e, pocket_gap(b, S[sd], np.array(head(BN[sd]["forearm"])), up, rt if sd == "Right" else -rt, STOCK_RM,
                         UA_R[sd], T, co[UA_V[sd]], front)


def rear_end(C4, S=None):
    """(rear end, front end, side) of the prop: the end nearest a shoulder joint."""
    S = S or {s_: np.array(head(BN[s_]["upper_arm"])) for s_ in ("Left", "Right")}
    E2 = [np.array(C4 @ Vector(e_)) for e_ in _END_L]
    b, sd = min(((e_, s_) for e_ in E2 for s_ in S), key=lambda x: np.linalg.norm(x[0] - S[x[1]]))
    return b, (E2[1] if b is E2[0] else E2[0]), sd


REST_LIM = POCKET_REST * HT / REF_HEIGHT


# the faces, regions and sides collisions.skin_tree takes, once: picked again for every candidate they took 55 of its
# 94 ms (object-array compares and 38k Vectors; the tree itself builds in 6 ms)
_F_SKIN = tris[(LAB_ALL[tris] != "").all(1)]
F_SKIN = faces_on(_F_SKIN.tolist()); REG_SKIN, SIDE_SKIN = LAB_ALL[_F_SKIN[:, 0]], SIDE_V[_F_SKIN[:, 0]]


def prop_depth(co, C4, pocket_=False):
    """(deepest prop point in the skin `co` outside the grip zone [m], region), as the audit's prop_in_body. While aiming
    from the armpit (`pocket_`) the stock's rest in the pocket counts only past REST_LIM, as the audit's prop_in_pocket."""
    hold = {s_[0]: (head(BN[s_]["hand"]), (head(BN[s_]["hand"]) - head(BN[s_]["forearm"])).length) for s_ in ("Left", "Right")}
    rest = None
    if pocket_: b, fr, sd = rear_end(C4); rest = (b, fr, sd[0], head(BN[sd]["upper_arm"]), head(BN[sd]["forearm"]))
    dd = prop_in_body(tree_on(co, F_SKIN), REG_SKIN, SIDE_SKIN, prop_pts(C4), hold, rest=rest)
    if "pocket" in dd:
        d_, p_ = dd.pop("pocket")
        if d_ > REST_LIM: dd["pocket"] = (BODY_LIM + d_ - REST_LIM, p_)   # past its limit = past prop_in_body's
    k_ = max(dd, key=lambda x: dd[x][0]) if dd else ""
    return (dd[k_][0] if dd else 0.0, k_)


def body_depth(C4, pocket_=False):
    """body_check on the current pose (arms as set, not as keyed)."""
    return prop_depth(vertices(body, bpy.context.evaluated_depsgraph_get()), C4, pocket_)


def prop_hits(C4, tr, pin=False):
    """Prop samples inside the body volume. While the rear end rests in the armpit (`pin`) the stock's rear span is left to
    the pocket checks: the arm closed over it in one pass flagged the frame and the next pass swung the stock straight
    ahead again (Kusznik round 8: 9 hits on the author's accepted aim)."""
    R = np.array(C4.to_3x3()); pts = (SAMP[~REAR_M] if pin else SAMP) @ R.T + np.array(C4.translation); n = 0
    for q in pts.tolist():
        loc, nor, _, d = tr[0].find_nearest(q, 0.15)
        if loc is None or d <= 0.008: continue
        p = Vector(q)
        if (p - loc).dot(nor) < 0 and inside(tr[0], p): n += 1
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
    if e < 1e-3 or A.keep_prop: continue
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
    d["chest"] = head(PROF.spine[-1]); d["Rchest"] = wrot(PROF.spine[-1]); d["hips"] = head(PROF.bone("hips"))
    d["prop"] = AW @ pb(PN).matrix @ CR_IN_BONE   # the prop as the GLB holds it (--keep-prop)
    K[f] = d
zR = np.array([K[f]["Rightpalm"].z for f in all_frames])
z_lo, z_hi = np.median(zR[:8]), np.percentile(zR, 92)
W_AIM = {}
AIM = MO.get("aim", {})
# where the prop's rear end rests while aiming, by skeleton roles: "shoulder" (default: butt_from_shoulder, pushed out of
# the body forward) or "armpit" (between the ribs and the inner upper arm below the shoulder joint; also implied by
# `butt_push`). In the armpit the prop is the target: its rear end is pinned in the pocket found on this frame's body, the
# search only turns the prop about it, and both arms are fitted to it. Kusznik round 6 (fixed body, prop pushed out and
# moved by the search) ended with the butt on the right forearm in front of the elbow
REST = AIM.get("rest_at", "armpit" if "butt_push" in AIM else "shoulder")
UNDER = REST == "armpit"
# The aim's frames: from the right hand's height over the clip, as long as the stock goes to the shoulder (the hand
# rises with it). Under the armpit the hand stays low (Kusznik: 21 cm in the hold, 23 cm on the aim pose, 47 cm in the
# recoil): there they come from the motion file (the `aim` key pose, the phases, the shot: lib/prop_path.py). The
# motion file's window on a shoulder aim too took the approved Mixamo Kusznik from 5.16 to 7.89 (the stock at the
# shoulder on frame 44 instead of 85% of the way)
AIM_WIN = aim_window(MO.get("phases"), MO.get("key_poses"), FPS, (MO.get("recoil") or {}).get("fire_s")) if UNDER else None
for f in all_frames:
    x = float(np.clip((K[f]["Rightpalm"].z - z_lo) / max(z_hi - z_lo, 1e-6), 0, 1)); W_AIM[f] = x * x * (3 - 2 * x)
    if AIM_WIN: W_AIM[f] = aim_weight(f, AIM_WIN)
    # walk/idle with the prop in both hands: hand height from arm swing would "aim" - the whole clip is a hold
    if MO.get("no_aim"): W_AIM[f] = 0.0
print("aim: %s; frames past half of it: %s" % (
    "rise %.0f -> %.0f (key pose `aim`), full to %.0f, down to %.0f" % AIM_WIN if AIM_WIN else "from the right hand's height",
    (lambda on: "%d-%d" % (on[0], on[-1]) if on else "-")([f for f in all_frames if W_AIM[f] >= 0.5])))
# head slightly back while aiming: makes room for the stock and the right elbow
HEAD_BACK = AIM.get("head_back_deg", 0)
BUTT_PUSH = Vector(AIM.get("butt_push", tuple(FWD))).normalized()
BUTT_SIDE = "Right" if BUTT_PUSH.dot(RIGHT) >= 0 else "Left"   # the arm whose armpit holds the butt

# ---------- approved key poses: where they hold the prop is the target ----------
# The search placed the prop from the body alone, frame by frame, and the clip did not show what was approved: on
# Kusznik's aim frame the rear end sat 11 cm higher under the arm than on the approved pose, on the hold frame 10 cm
# further out. The prop of each key pose is read against that pose's body and carried onto every frame's body
# (prop_path.carry): a hold pose follows the hips, an aim pose the chest at the butt-side shoulder joint. The stock's
# direction stays the approved one (carried with the chest it swung with every twist of the torso).
KEYP = {}   # key frame -> dict(C prop pose, S butt-side shoulder joint, Rc chest rotation, hips) on the approved pose
if A.poses and not A.keep_prop:
    _had = {c_: set(getattr(bpy.data, c_)) for c_ in ("objects", "meshes", "armatures", "actions", "materials", "images", "textures")}
    bpy.ops.import_scene.gltf(filepath=A.poses)
    _arm2 = next(o for o in bpy.data.objects if o not in _had["objects"] and o.type == "ARMATURE")
    _act2 = next((a_ for a_ in bpy.data.actions if a_ not in _had["actions"] and a_.name.split(".")[0] == MO["action"].split(".")[0]), None)
    if _act2 is None: raise SystemExit("--poses %s: no action '%s'" % (A.poses, MO["action"]))
    for _pb in _arm2.pose.bones: _pb.matrix_basis = Matrix()
    _arm2.animation_data.action = _act2; _w2 = lambda n: _arm2.matrix_world @ _arm2.pose.bones[pb(n).name].matrix
    for _n, _fk in MO.get("key_poses", {}).items():
        if _n.startswith("_") or not _act2.frame_range[0] <= _fk <= _act2.frame_range[1]: continue
        sc.frame_set(int(_fk))
        KEYP[int(_fk)] = dict(C=_w2(PN) @ CR_IN_BONE, S=_w2(BN[BUTT_SIDE]["upper_arm"]).translation.copy(),
                              Rc=_w2(PROF.spine[-1]).to_3x3().normalized(), hips=_w2(PROF.bone("hips")).translation.copy())
    for o in [o for o in bpy.data.objects if o not in _had["objects"]]: bpy.data.objects.remove(o, do_unlink=True)
    for c_, was in _had.items():   # nothing of the poses file stays: the export writes every action and mesh it finds
        if c_ != "objects":
            for d_ in [d_ for d_ in getattr(bpy.data, c_) if d_ not in was]: getattr(bpy.data, c_).remove(d_)
    arm.animation_data.action = act
KEY_AIM = sorted(k_ for k_ in KEYP if W_AIM.get(k_, 0.0) >= 0.5); KEY_HOLD = sorted(k_ for k_ in KEYP if k_ not in KEY_AIM)
# the approved poses' arms too (grip roll and elbow plane, from the <glb>_arms.json written with them): on the key frames
# the clip took its own (Kusznik's hold: left grip rolled -20 where the approved pose has +20, right elbow plane -15 for -60)
KEYARMS = {}
if KEYP and os.path.exists(A.poses.replace(".glb", "_arms.json")):
    for k_, v_ in json.load(open(A.poses.replace(".glb", "_arms.json"), encoding="utf-8")).items():
        if int(k_) in KEYP: KEYARMS[int(k_)] = {s_: (v_[s_]["roll"], v_[s_]["elbow"]) for s_ in ("Left", "Right") if "roll" in v_.get(s_, {})}
if A.poses: print("approved key poses %s: hold on fr. %s, aim on fr. %s" % (os.path.basename(A.poses), KEY_HOLD or "-", KEY_AIM or "-"))


def carried(f, aim):
    """The prop on frame f as the nearest approved key pose of its kind holds it (None without one)."""
    k_ = nearest(f, KEY_AIM if aim else KEY_HOLD)
    if k_ is None: return None
    kp = KEYP[k_]; C = kp["C"].copy(); k = K[f]
    if aim:   # the rear end keeps its place on the chest under the shoulder joint
        b_ = carry(C @ Vector((BUTT, 0, 0)), kp["S"], np.array(kp["Rc"]), k[BUTT_SIDE + "S"], np.array(k["Rchest"]))
        C.translation += Vector(b_) - C @ Vector((BUTT, 0, 0))
    else: C.translation = Vector(carry(C.translation, kp["hips"], None, k["hips"]))
    return C
for f in all_frames:
    if not HEAD_BACK or W_AIM[f] < 1e-3 or A.keep_prop: continue
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
    # the palm stands off the stock across its axis: a palm normal tilted along the stock (Kusznik's left hand on the
    # author's aim, 0.46 along it) moved the palm along the stock too, and the knuckle offset below took the grip's whole
    # position on the axis into its push (0.46 x 0.56 m): the left palm ended 20 cm off the stock
    perp = lambda v: v if abs(v.dot(ax[0])) < 1e-3 else (v - ax[0] * v.dot(ax[0])).normalized()
    palm = C4.translation + ax[0] * g["x"] - perp(n) * (RS[side] + GP["clearance"])
    Rh = hand_R(side, d, n)
    if g.get("knuckles_at_edge") and side in KOFF:
        # knuckles under the middle of the stock: the first phalanx will not bend up (it would enter the stock), fingers went sideways.
        # Put the knuckles (from the hand rest pose) on the stock corner: towards the fingers s and underneath (-n), half a finger off the wall
        s = d - ax[0] * d.dot(ax[0]) - n * d.dot(n)
        if s.length > 1e-3:
            s.normalize(); R3 = C4.to_3x3().transposed(); m = stockm & (np.abs(Lc[:, 0] - g["x"]) < 0.03)
            kn = palm - d * PALM + Rh @ KOFF[side] - C4.translation
            for v in (perp(s), perp(-n)):
                e = float((Lc[m, 1:] @ np.array((R3 @ v)[1:])).max())
                palm = palm + v * (e + 0.5 * GP["finger_thickness"] - kn.dot(v))
    return palm - d * PALM, Rh, palm


def ranges(side):
    """How far the grip may roll around the stock and the elbow around the shoulder-wrist axis (deg)."""
    return GR[side].get("roll_deg", 20), GP["elbow_deg"]


def solve_arm(side, f, C4, tr, rolls=(0,), poles=(0,), all_=False, memo=None):
    """Cheapest arm setup over the grid (grip roll x elbow plane); `all_` = list of (cost, roll, elbow). `memo` = setups
    already measured for this prop pose on this frame's trees ({(side, roll, elbow): setup}): each is measured once."""
    k = K[f]; Sp, E0, W0 = k[side + "S"], k[side + "E"], k[side + "W"]
    la, lb = (E0 - Sp).length, (W0 - E0).length
    best = None; PP = None
    for roll in rolls:
        known = [] if memo is None else [memo.get((side, roll, pa)) for pa in poles]
        if known and None not in known:
            for b in known:
                if best is None or b["cost"] < best["cost"]: best = b
            continue
        if PP is None and ARM_COLL: PP = prop_pts(C4)
        Wt, Rh, palm = grip(side, C4, roll)
        PF = PP[np.linalg.norm(PP - np.array(Wt), axis=1) > WRIST_FREE] if ARM_COLL else None
        dist = min((Wt - Sp).length, (la + lb) * 0.999); dr = (Wt - Sp).normalized()
        pole0 = (E0 - Sp) - dr * (E0 - Sp).dot(dr)
        if pole0.length < 1e-6: pole0 = -UP - dr * (-UP).dot(dr)
        pole0.normalize()
        ca = max(-1, min(1, (la * la + dist * dist - lb * lb) / (2 * la * dist)))
        for i_, pa in enumerate(poles):
            if known and known[i_] is not None:
                if best is None or known[i_]["cost"] < best["cost"]: best = known[i_]
                continue
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
            # own skeleton: the arm stays a little bent (REACH_SLACK of its length short of straight); at 400/m the left
            # hand reached 2.3 cm past a straight arm with the wrist turned 47 deg (author: "reaches unnaturally far")
            if ARM_COLL: cost += 4000 * max(0.0, reach + REACH_SLACK * (la + lb))
            parm = 0.0
            if ARM_COLL:
                ua = tr[3].get((side, "upper_arm")); Rua = q1.to_matrix() @ k[side + "Rua"]
                if side == BUTT_SIDE and pinned(f):   # the stock resting in the pocket may sink into the closed upper arm
                    # up to REST_LIM, as the audit's prop_in_pocket; charged from 0 the arm never closed over the stock
                    # and the solver missed the author's aim (Kusznik round 8: 4.7 cm "in the arm" on the accepted pose).
                    # Only in the armpit fold (the arm's top POCKET_ARM): exempt along the whole arm, the elbow closed on
                    # the stock (3.3 cm in the arm's middle, author: "it goes into the elbow, not the armpit")
                    fold = REAR_M & (((PP - np.array(Sp)) @ np.array(Rua))[:, 1] <= POCKET_ARM * la)
                    parm = max(arm_depth(ua, Rua, Sp, PP[~fold]), max(0.0, arm_depth(ua, Rua, Sp, PP[fold]) - REST_LIM))
                else:
                    parm = arm_depth(ua, Rua, Sp, PP)
                parm = max(parm, arm_depth(tr[3].get((side, "forearm")), Rfa3, En, PF))
            cost += 4000 * parm   # 40 per cm of prop inside the arm, as one collision point
            cost += 0.05 * abs(pa)
            et = GR[side].get("elbow_target")   # [outward, forward, up] while aiming
            if et:
                out_ = RIGHT if side == "Right" else -RIGHT
                tc = out_ * et[0] + FWD * et[1] + UP * et[2]; tc = tc - dr * tc.dot(dr)
                eo = (En - Sp) - dr * (En - Sp).dot(dr)
                if tc.length > 1e-6 and eo.length > 1e-6:
                    cost += GR[side].get("elbow_target_weight", 80) * W_AIM[f] * (1 - eo.normalized().dot(tc.normalized()))
            if all_: best = (best or []) + [(cost, roll, pa)]; continue
            if memo is not None or best is None or cost < best["cost"]:
                b = dict(cost=cost, roll=roll, pa=pa, q1=q1, Rfa3=Rfa3, Rh=Rh, bend=bend, twist=twist, coll=coll, reach=reach,
                         parm=parm, slack=max(0.0, reach + REACH_SLACK * (la + lb)))
                if memo is not None: memo[(side, roll, pa)] = b
                if best is None or cost < best["cost"]: best = b
    return best


POCKET_DEPTH = (0.15, 0.25, 0.35, 0.45)   # the armpit's hollow is searched this far below the shoulder joint (x upper arm)
POCKET_INFO = {}
STOCK_R = r_at(BUTT + 0.03)
SKIN_W = 3000   # own skeleton: cost per metre of prop (or limb past its limit, or rear end off the pocket) on the real skin
# Kusznik, author's accepted aim (round 8, the solver's r7 missed it): the stock 0.67-0.72 of the upper arm below the
# shoulder, 18 deg off straight ahead, crossing the pocket 12-20 cm before its rear end (14 cm behind the shoulder joint)
POCKET_TRY = (0.3, 0.42, 0.54, 0.66)   # pocket depths below the shoulder joint tried while aiming [x upper arm]
AIM_FREE = 20   # deg the stock may yaw, pitch or roll off the aim about a pinned rear end before it costs 10x
STOCK_SLIDE = POCKET_SPAN * float(Lc[:, 0].max() - BUTT)   # how far the stock may slide back through the pocket [m]
REAR_M = SAMP[:, 0] <= BUTT + STOCK_SLIDE   # prop samples in the stock's rear span (the part that may rest in the pocket)
POCKET_FW = (0.0, 0.06, 0.12)   # pinned search starts: the pocket this far in front of the shoulder joint [m]
POCKET_SLIP = 0.03   # how far the rear end may leave the pocket's centre while aiming [m]
NX = 6 if UNDER else 4   # pose offset: translation + yaw (+ pitch and roll about a pinned rear end)


def pose_cost(C4, f, tr, arms=None, memo=None, over=None):
    """Cost of a prop pose from the body volume and both arms. `memo` = what this frame's search has already measured
    for this pose; `over(c)` = a pose costing at least c cannot win: measuring stops and None is returned (every part
    of the cost is >= 0, so the sum so far is a floor)."""
    if memo is None: memo = {}
    if over and over(0): return None
    if "hits" not in memo: memo["hits"] = prop_hits(C4, tr, pinned(f))
    c = 50 * memo["hits"]
    for side in ("Right", "Left"):
        if over and over(c): return None
        # a grid of 5 grips x 3 elbows instead of one setup was tried: audit score 15.5 -> 23.4, worse
        # under the armpit the arm next to the butt opens round it: its elbow plane is searched here too, else the search
        # moved the prop out of a closed arm (Kusznik: butt 5-7 cm out, on the forearm)
        pl = range(-ranges(side)[1], ranges(side)[1] + 1, 15) if UNDER else (0,)
        if side == BUTT_SIDE and FORCE_POLE: pl = FORCE_POLE
        b = solve_arm(side, f, C4, tr, poles=pl, memo=memo); c += 20 * b["coll"] + 400 * max(0, b["reach"]) + 2000 * b["parm"]
        # own skeleton: the prop's place also keeps both grips REACH_SLACK short of a straight arm (only the elbow plane
        # did): the search put Kusznik's left hand 0.7 cm short of straight where the author's aim keeps it 4.1 cm short
        if ARM_COLL: c += 500 * b["slack"]   # soft: at 2000/m the right hand sank 2.5 cm into the hip in the hold
        if ARM_COLL and side == BUTT_SIDE and pinned(f):
            # the stock under this arm: the elbow swings out, away from the torso (ELBOW_OUT of the upper arm out of the
            # shoulder joint), so the stock runs through the armpit. Kusznik round 8: the motion's elbow (down) stayed
            # 13 cm out, the stock lay in the elbow (author: "the elbow is too close to the body, the crossbow goes into
            # the elbow instead of the armpit; just swing the elbow out"; their elbow 20 cm out). Swung out after the
            # prop was placed, the arm's fold pressed the stock deeper: it is chosen with the prop's place
            Sp_, E0_ = K[f][side + "S"], K[f][side + "E"]; out_ = RIGHT if side == "Right" else -RIGHT
            c += ELBOW_W * max(0.0, ELBOW_OUT * (E0_ - Sp_).length - (b["q1"] @ (E0_ - Sp_)).dot(out_))
        if arms is not None: arms[side] = b
    return c


ELBOW_OUT, ELBOW_W = 0.6, 300   # pinned: the butt-side elbow this far out of the shoulder joint [x upper arm], cost per m short
FORCE_POLE = []   # pinned search: the butt-side elbow plane(s) tried on the real skin
# An approved place is kept as it is on every frame where it costs at most CLEAN more than on its own key frame (the cost
# of 4 mm of prop in the skin): what was approved there is good enough here. A fixed limit kept it nowhere on Kusznik's
# aim: on the key frame itself it costs 140 (the right arm 3 points close to the ribs, the left arm nearly straight),
# the search moved it 3 cm and 5 deg off and the clip did not show the approved pose on the approved frame.
CLEAN = 12.0
REF = {}          # (pass, key frame) -> what the approved place costs on the key frame itself
PASS = [0]
TGT = {}          # frames with an approved place: (its cost there, after the search near it, in another pocket)
COSTF = {}        # frame -> cost of its answer in the last search


def ref_cost(f, pin):
    """What the approved place costs on the key frame that frame f's place comes from (this pass's body)."""
    k_ = nearest(f, KEY_AIM if pin else KEY_HOLD)
    if k_ not in BASE or pinned(k_) != pin: return 0.0   # a quick try without the key frame
    if (PASS[0], k_) not in REF: REF[(PASS[0], k_)] = best_plane(BASE[k_][0], k_, TR[k_]); ON_FRAME[0] = None
    return REF[(PASS[0], k_)]


def best_plane(C4, f, tr, memo=None):
    """Cost of a prop pose with the butt-side elbow plane chosen on the real skin (free, or one of the outward planes),
    as the search chooses it; LAST_ARMS is left at the chosen one. Left to the arm's own cost, Kusznik's approved aim got
    the right elbow plane +45 deg where the approved pose and the search have -45."""
    COST = skin_cost if ARM_COLL else pose_cost; memo = {} if memo is None else memo; best = None
    planes = (([],) + tuple([p_] for p_ in range(-ranges(BUTT_SIDE)[1], 1, 15))) if pinned(f) and ARM_COLL else ([],)
    if pinned(f) and ARM_COLL and BUTT_SIDE in KEYARMS.get(f, {}): planes = ([KEYARMS[f][BUTT_SIDE][1]],)   # a key frame: the approved plane
    for pl_ in planes:
        FORCE_POLE[:] = pl_; c = COST(C4, f, tr, memo)
        if best is None or c < best[0]: best = (c, list(pl_))
    FORCE_POLE[:] = best[1]; COST(C4, f, tr, memo); FORCE_POLE[:] = []
    return best[0]
LAST_ARMS = {}   # arm setups of the last skin_cost
ARMS_FIX = {}    # pinned frames: {f: {side: (roll, elbow)}} measured on the real skin, kept by path()


SKIN_MODS = [m for o in skinned for m in o.modifiers if m.type == "ARMATURE"]
ON_FRAME = [None]   # the frame whose animation the scene holds with only the arm bones moved since (a search in progress)
COUNT = dict(asked=0, skin=0, known=0, kept=0)   # search: prop poses asked for, measured on the skin, known already; frames kept


def arms_to_scene(f, arms):
    """Both arms of a candidate into the scene, the skin deformed once. Each bone needs the pose of the one above it, so
    the scene is updated after each of the six: with the armature modifiers off meanwhile, those updates move bones only
    (the skin was deformed seven times per candidate, six of them never read: 4.4 -> 3.1 ms). The frame is set once per
    search: the search moves these six bones alone and every call sets all six again."""
    if ON_FRAME[0] != f: sc.frame_set(f); ON_FRAME[0] = f
    for m in SKIN_MODS: m.show_viewport = False
    for side, b in arms.items():
        setw(BN[side]["upper_arm"], b["q1"].to_matrix() @ K[f][side + "Rua"]); setw(BN[side]["forearm"], b["Rfa3"]); setw(BN[side]["hand"], b["Rh"])
    for m in SKIN_MODS: m.show_viewport = True
    bpy.context.view_layer.update()


def skin_cost(C4, f, tr, memo=None, over=None):
    """pose_cost plus the audit's prop_in_body on the real skin with both arms set by their IK. The arm capsules and the
    body volume alone saw no contact where the audit found the stock 7 cm in the torso and the upper arm round the pocket.
    `memo`, `over`: as pose_cost; the skin is measured once per prop pose and pair of arm setups."""
    if memo is None: memo = {}
    arms = {}; c = pose_cost(C4, f, tr, arms, memo, over)
    if c is None or (over and over(c)): return None
    LAST_ARMS.clear(); LAST_ARMS.update({side: (b["roll"], b["pa"]) for side, b in arms.items()})
    key = ("skin",) + tuple(LAST_ARMS[side] for side in ("Right", "Left")); m = memo.get(key)
    if m is None or (m[1] is None and not (over and over(c + SKIN_W * m[0]))):
        COUNT["skin"] += 1; arms_to_scene(f, arms); co = vertices(body, bpy.context.evaluated_depsgraph_get())
        d_ = prop_depth(co, C4, pinned(f))[0] if m is None else m[0]; m = memo[key] = (d_, None, None)
        if not (over and over(c + SKIN_W * d_)):   # the limbs and the pocket only add to it
            m = memo[key] = (d_,) + limbs_excess(co, C4 if pinned(f) else None)
    else: COUNT["known"] += 1
    if m[1] is None: return None
    d_, e_, g_ = m
    return c + SKIN_W * (d_ + e_ + max(0.0, g_ - 0.5 * POCKET_LIM * BODY_LIM / METRICS["prop_in_body"][0]))


def pinned(f): return UNDER and W_AIM[f] >= 0.5   # aiming with the rear end in the armpit


def cost_parts(C4, f, tr):
    """What a prop pose costs, part by part (the quick try says it for the approved place)."""
    memo = {}; arms = {}; pose_cost(C4, f, tr, arms, memo); t = "prop points in the body %d" % memo["hits"]
    if memo["hits"]:   # where: the region of the skin nearest to each
        reg_ = {}
        for q in ((SAMP[~REAR_M] if pinned(f) else SAMP) @ np.array(C4.to_3x3()).T + np.array(C4.translation)).tolist():
            loc, nor, i_, d = tr[0].find_nearest(q, 0.15)
            if loc is not None and d > 0.008 and (Vector(q) - loc).dot(nor) < 0 and inside(tr[0], Vector(q)):
                reg_[str(_REG_BODY[i_])] = reg_.get(str(_REG_BODY[i_]), 0) + 1
        t += " (%s)" % ", ".join("%s %d" % kv for kv in sorted(reg_.items()))
    for side, b in arms.items():
        t += "; %s arm: %d points in the body, prop %.1f cm in it, %.1f cm past its slack" % (
            SIDE_NAME[side], b["coll"], 100 * b["parm"], 100 * b["slack"])
    if ARM_COLL:
        skin_cost(C4, f, tr, memo); d_, e_, g_ = memo[("skin",) + tuple(LAST_ARMS[s_] for s_ in ("Right", "Left"))]
        t += "; on the skin: prop %.1f cm in it, limbs %.1f cm past their limits, rear end %.1f cm off the pocket" % (100 * d_, 100 * e_, 100 * g_)
    return t


def shift(C4, x, f=None):
    """x = (right, up, forward, yaw in deg); yaw around the right-hand grip. While the rear end rests in its pocket
    (pinned) the prop turns about it: x = (right, up, forward, yaw, pitch, roll about the stock in deg)."""
    if f is not None and pinned(f):
        pv = C4 @ Vector((BUTT, 0, 0)); st = C4.to_3x3().col[0].normalized(); lat = st.cross(UP).normalized()
        R = (Quaternion(UP, math.radians(x[3])) @ Quaternion(lat, math.radians(x[4]))
             @ Quaternion(st, math.radians(x[5]))).to_matrix().to_4x4()
        C2 = Matrix.Translation(pv) @ R @ Matrix.Translation(-pv) @ C4
    else:
        C2 = (Matrix.Translation(C4.translation) @ Quaternion(UP, math.radians(x[3])).to_matrix().to_4x4()
              @ Matrix.Translation(-C4.translation) @ C4)
    C2.translation += RIGHT * x[0] + UP * x[1] + FWD * x[2]
    return C2


def search(C4, f, tr, seed=None, like=None):
    """Coordinate descent in both directions (an old grid only in +: the left elbow stayed in the torso).
    `seed` = the offset of the frame next to this one (or this frame's own from the pass before): the search starts there
    when that costs less than no offset. `like` = (elbow plane, cost) of that neighbour's answer: when the same offset
    and plane cost here at most CLEAN more than there, this frame holds the prop the same way and nothing is searched."""
    # offset with a limit and a stronger penalty: at 30/m without a limit the crossbow escaped collisions 37 cm above the head at the shot
    MX, KP = GP.get("max_offset", 0.08), GP.get("offset_penalty", 100)
    pin = pinned(f)
    # pinned: the rear end stays within POCKET_SLIP of its pocket. Turning only about it (no slip) the stock found no
    # room in front of the chest and swung 60 deg out to the side; 2 cm off the ribs it points 10 deg in, no contact
    if pin: MX = POCKET_SLIP
    # own skeleton / under the arm: the real skin as the audit sees it (the volume without arms is open at the shoulders:
    # its inside test missed the stock 7.7 cm deep in the front armpit fold)
    COST = skin_cost if ARM_COLL else pose_cost

    st_ = C4.to_3x3().col[0].normalized()

    known = {}   # prop pose -> what was measured for it (arm setups, body hits, skin depths): this frame, these trees

    def cost(x, Cb=C4, a0=(0.0, 0.0), bound=None, far=0.0):
        """`bound`: the cost to beat. A pose that cannot is not measured to the end and comes back as 1e9.
        `far`: what the start Cb already costs for its distance from the approved place."""
        d = math.sqrt(x[0] ** 2 + x[1] ** 2 + x[2] ** 2)
        if pin:   # the stock may also slide back through the pocket by up to STOCK_SLIDE (the front hand reaches less far)
            sb = Cb.to_3x3().col[0].normalized(); t = RIGHT * x[0] + UP * x[1] + FWD * x[2]; al = t.dot(sb)
            d = (t - sb * al).length + max(0.0, al) + max(0.0, -al - STOCK_SLIDE)
        if d > MX + 1e-9: return 1e9
        if pin:   # the aim stays ahead: yaw or pitch (with the start's turn a0) past AIM_FREE costs 10x (free, the stock
            # swung 50-60 deg out or 40 up)
            ang = [x[3] + a0[0], x[4] + a0[1]] + list(x[5:])
            # the roll about the stock too: free, it grew frame by frame to 60 deg where each frame starts from its
            # neighbour's answer (Kusznik, frames 58-64: the bow stood on its side)
            turn = 0.3 * sum(abs(v) for v in ang) + 3 * sum(max(0.0, abs(v) - AIM_FREE) for v in ang[:3])
        else:
            turn = 0.3 * sum(abs(v) for v in x[3:])
        kd = KP * d + far; C2 = shift(Cb, x, f); COUNT["asked"] += 1
        c = COST(C2, f, tr, memo=known.setdefault(tuple(v for r in C2 for v in r), {}),
                 over=None if bound is None else lambda c_: c_ + kd + turn >= bound)
        return 1e9 if c is None else c + kd + turn
    # the approved place first (--poses). One that is clean on this frame's body is kept as it is: every frame then holds
    # the prop the same way and the average over neighbours is theirs too. The search from the body alone gave each
    # frame its own of 108 pockets, each clean, and their average ended 2-9.5 cm in the body (Kusznik, frames 54-86)
    tgt = (f in TARGETED) if pin else bool(KEY_HOLD)
    x0 = None
    if tgt:
        at0 = known.setdefault(tuple(v for r in C4 for v in r), {})
        c0 = best_plane(C4, f, tr, at0); COUNT["asked"] += 1; TGT[f] = (round(c0, 1),)
        if A.frames: print("fr. %d: the approved place costs %.1f: %s" % (f, c0, cost_parts(C4, f, tr)))
        fine = ref_cost(f, pin) + CLEAN
        if like is not None:
            # as the neighbour holds it. Frames solved alone took unrelated elbow planes of nearly the same cost (Kusznik's
            # right elbow: -30, -15, -45, -30, -15, -45 deg on frames 40-47) and the average over them was nobody's
            s_ = list(seed) if seed is not None else [0.0] * NX
            if pin and like[0] is not None: FORCE_POLE[:] = [like[0]]
            c1 = cost(s_, bound=like[1] + CLEAN + 1e-6); FORCE_POLE[:] = []
            if c1 <= like[1] + CLEAN:
                if pin and COST is skin_cost: ARMS_FIX[f] = dict(LAST_ARMS)
                TGT[f] += (round(c1, 1), "as the frame next to it"); COSTF[f] = c1
                return (shift(C4, s_, f) if any(s_) else C4), s_
        c0 = best_plane(C4, f, tr, at0)   # again: LAST_ARMS is this pose's
        if c0 <= fine:
            if pin and COST is skin_cost: ARMS_FIX[f] = dict(LAST_ARMS)
            COSTF[f] = c0; return C4, [0.0] * NX
        if seed is not None and any(seed) and cost(list(seed), bound=c0) < c0: x0 = list(seed)

    def tries_from(Cb, yw0, far=0.0, x0=None):
        """Descents from the start Cb (offset x0) with each elbow plane next to the pocket -> (cost, x, plane)."""
        cst = lambda x, Cb_=Cb, bound=None: cost(x, Cb_, (yw0, 0.0), bound, far)
        # the elbow plane next to the pocket is chosen on the real skin too: by the arm cost alone the arm stayed in
        # front of the chest and the butt ended outside it, or the arm closed through the butt
        tries = []
        for pl_ in ([],) + tuple([p_] for p_ in range(-ranges(BUTT_SIDE)[1], 1, 15)) if COST is skin_cost else ([],):
            FORCE_POLE[:] = pl_; x_, b_ = descend(cst, Cb, pin, NX, x0); tries.append((b_, x_, list(pl_)))
            if b_ == 0: break   # nothing costs less, and ties go to the first
        FORCE_POLE[:] = []
        return min(tries, key=lambda t: t[0])
    if pin:   # start from the pocket at every depth to try: just under the shoulder the stock ran into the front armpit fold
        b0 = C4 @ Vector((BUTT, 0, 0)); starts = []; low = None; kept = None
        if tgt:   # from the approved place; other pockets only when no way near it is clean, and they pay their distance
            kept = tries_from(C4, 0, x0=x0) + (C4,); TGT[f] += (round(kept[0], 1),); low = kept[0]
        across = 1 if BUTT_SIDE == "Right" else -1   # + yaw turns the stock towards the character's left
        # ties (many starts cost 0) go to the first: deepest, at the side, half slid back, straight. Kusznik, author's
        # accepted aim (round 8): the stock lies along the front of the ribs 0.66 of the upper arm below the shoulder joint
        # (2-4 cm off the torso 20-44 cm before its rear end), 18 deg across the chest, its rear end out under the upper
        # arm. The solver started only with the rear end at the side of the ribs, turned about that end: the turn swung
        # the stock's middle into the chest and the descent (3 cm round its start) stayed straight ahead (cost 37 vs 0)
        for dep in reversed(POCKET_TRY) if kept is None or kept[0] > CLEAN else ():
            for fw in POCKET_FW:
                p_ = pocket(f, BUTT_SIDE, (dep,), (fw,), strict=True)
                if p_ is None: continue
                for sl in (0.5, 1.0, 0.0):   # a section of the stock's rear part in the pocket instead of its end
                    for yw in (0, across * AIM_FREE, -across * AIM_FREE):   # turned about the pocket, not the rear end
                        Cs = C4.copy(); Cs.translation += p_ - b0 - st_ * (sl * STOCK_SLIDE)
                        far = KP * (Cs.translation - C4.translation).length if tgt else 0.0
                        if yw: Cs = Matrix.Translation(p_) @ Quaternion(UP, math.radians(yw)).to_matrix().to_4x4() @ Matrix.Translation(-p_) @ Cs
                        starts.append((cost([0.0] * NX, Cs, (yw, 0.0), low, far), Cs, yw, dep, fw, far))
                        low = starts[-1][0] if low is None else min(low, starts[-1][0])
        if not starts and kept is None:
            Cs = C4.copy(); Cs.translation += pocket(f, BUTT_SIDE) - b0; starts = [(0.0, Cs, 0, None, None, 0.0)]
        if starts and (kept is None or min(starts, key=lambda t: t[0])[0] < kept[0]):
            _, Cb, yw0, dep, fw, far = min(starts, key=lambda t: t[0])
            if dep is not None: pocket(f, BUTT_SIDE, (dep,), (fw,), strict=True)   # POCKET_INFO of the chosen start
            other = tries_from(Cb, yw0, far) + (Cb,)
            if kept is None or other[0] < kept[0]:
                kept = other
                if tgt: TGT[f] += (round(other[0], 1), "other pocket")
        best, x, pl_, Cb = kept; FORCE_POLE[:] = pl_; COSTF[f] = best
        C2 = shift(Cb, x, f); x = unshift(C4, C2)
        if COST is skin_cost: skin_cost(C2, f, tr, known.get(tuple(v for r in C2 for v in r))); ARMS_FIX[f] = dict(LAST_ARMS)
        FORCE_POLE[:] = []
        return C2, x
    x, best = descend(cost, C4, pin, NX, x0); COSTF[f] = best
    if tgt: TGT[f] += (round(best, 1),)
    return (C4 if best == 0 and not any(x) else shift(C4, x, f)), x


def unshift(C4, C2):
    """x of a pinned frame with shift(C4, x, f) == C2 (yaw about up, pitch about the stock's side axis, roll about it)."""
    R4 = C4.to_3x3().normalized(); st = R4.col[0].normalized(); lat = st.cross(UP).normalized(); d1 = C2.to_3x3().normalized().col[0].normalized()
    el = lambda v: math.asin(max(-1.0, min(1.0, v.dot(UP))))
    h0, h1 = st - UP * st.dot(UP), d1 - UP * d1.dot(UP)
    a = math.atan2(h0.cross(h1).dot(UP), h0.dot(h1)); b = el(d1) - el(st)
    Q = Quaternion(UP, a) @ Quaternion(lat, b)
    r = Q.inverted() @ (C2.to_3x3().normalized() @ R4.inverted()).to_quaternion()
    c = 2 * math.atan2(Vector((r.x, r.y, r.z)).dot(st), r.w)
    x = [0.0, 0.0, 0.0, math.degrees(a), math.degrees(b), math.degrees(c)]
    pv = C4 @ Vector((BUTT, 0, 0)); R = (Q @ Quaternion(st, c)).to_matrix().to_4x4()
    t = C2.translation - (Matrix.Translation(pv) @ R @ Matrix.Translation(-pv) @ C4).translation
    x[0], x[1], x[2] = t.dot(RIGHT), t.dot(UP), t.dot(FWD)
    return x


def descend(cost, Cb, pin, nx, x0=None):
    T = (0.08, 0.04, 0.02)
    STEPS = (((0.02, 0.01),) * 2 + ((0.04, 0.02, 0.01),) + ((20, 10, 5), (10, 5), (10, 5))) if pin else (T, T, T, (20, 10, 5)) + ((),) * (nx - 4)
    return descend_steps(cost, Cb, STEPS, x0=x0)


HOLD = MO.get("hold")
TARGETED = set()   # frames whose aim comes from an approved key pose (--poses)


def out_of_body(p, direction, tree, clearance):
    """Moves a point along `direction` until it leaves the body volume with `clearance` to spare."""
    for _ in range(60):
        loc, nor, _, dd = tree.find_nearest(p, 0.3)
        if loc is None or ((p - loc).dot(nor) > 0 and dd > clearance): break
        p = p + direction * 0.01
    return p


def pocket(f, side, deps=None, fws=None, strict=False):
    """The armpit pocket on this frame's body, from roles: below the shoulder joint (POCKET_DEPTH of the upper arm) and
    around its front-back position, walking out from the chest's midline: where the torso ends and where the upper arm
    begins (two volumes: they overlap where the arm lies on the ribs). The widest gap wins; the butt goes to its middle,
    or the stock's radius off the ribs when it is narrower than the stock (it touches both). Walked out of a body without
    arms at one fixed spot the butt landed 2 cm outside the shoulder joint, through the arm and out of the back."""
    k = K[f]; S = k[side + "S"]; la = (k[side + "E"] - S).length; out = RIGHT if side == "Right" else -RIGHT
    tor, arm_t = TR[f][1], TR[f][2]
    ins = lambda tree, q: (lambda h: h[0] is not None and (q - h[0]).dot(h[1]) < 0)(tree.find_nearest(q, 0.3))
    best = None
    for dep in deps or POCKET_DEPTH:
        for fw in fws or (-0.08, -0.04, 0.0, 0.04, 0.08):
            p = S - UP * (dep * la) + FWD * fw; p = p - out * (p - k["chest"]).dot(out)
            qs = [p + out * (0.005 * i) for i in range(90)]; it = [ins(tor, q) for q in qs]; ia = [ins(arm_t, q) for q in qs]
            t_exit = next((i for i in range(1, 90) if it[i - 1] and not it[i]), None)
            if t_exit is None: continue
            a_in = next((i for i in range(90) if ia[i]), None)
            gap = 1.0 if a_in is None else 0.005 * (a_in - t_exit)
            g0 = qs[t_exit]; c = g0 + out * (gap / 2 if gap > 2 * STOCK_R and a_in is not None else STOCK_R)
            key = (min(gap, 2 * STOCK_R + 0.02), -abs(fw) - abs(dep - 0.3) * la)   # widest (enough) gap, then nearest the middle
            if best is None or key > best[0]: best = (key, c, gap, dep, fw)
    if best is None: return None if strict else out_of_body(S - UP * (0.3 * la), out, TR[f][1], STOCK_R)
    POCKET_INFO[f] = "gap %.1f cm at %.2f of the upper arm below the shoulder, %+.0f cm forward" % (100 * best[2], best[3], 100 * best[4])
    return best[1]


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
    k = K[f]; Ck = carried(f, False); Ca = carried(f, True)
    if Ck is not None: pass
    elif HOLD:
        sc.frame_set(f); Ck = hold_pose(f)
    else:
        Ck = frame3((k["Leftpalm"] - k["Rightpalm"]).normalized(), UP).to_4x4(); Ck.translation = k["Rightpalm"]
    kick = math.radians(RC["kick_deg"] * env(f)) if RC else 0.0; tilt = math.radians(AIM.get("pitch_deg", 0))
    w = W_AIM[f]
    if UNDER: w = min(1.0, 2 * w)   # in the pocket from half-aim on (pinned frames): there the butt is exactly at it
    if Ca is not None:   # the approved aim: the recoil turns it up about its rear end
        pv = Ca @ Vector((BUTT, 0, 0)); lat = Ca.to_3x3().col[0].normalized().cross(UP).normalized()
        Ca = Matrix.Translation(pv) @ Quaternion(lat, kick).to_matrix().to_4x4() @ Matrix.Translation(-pv) @ Ca
        TARGETED.add(f); return blend_pose(Ck, Ca, w), w
    fd = (FWD * math.cos(tilt - kick) + UP * math.sin(-tilt + kick)).normalized()
    butt = k["RightS"] + Vector(AIM.get("butt_from_shoulder", (0, -0.07, -0.03)))
    # the shoulder joint lies inside the body: the butt leaves it forward (stock on the shoulder) or along `butt_push`.
    # A stock under the armpit (Kusznik on amts, author 2026-11-19) pushed forward ended 10 cm in front of the chest.
    # Pushed sideways it leaves the torso alone: the upper arm closes over it (out of the whole body it went through the arm
    # and stopped 13 cm outside the shoulder joint)
    butt = out_of_body(butt, BUTT_PUSH, TR[f][1] if "butt_push" in AIM else TR[f][0], 0.01)
    if UNDER: butt = pocket(f, BUTT_SIDE)
    Ca = frame3(fd, UP).to_4x4(); Ca.translation = butt - fd * BUTT
    return blend_pose(Ck, Ca, w), w


def blend_pose(Ck, Ca, w):
    C = Ck.to_quaternion().slerp(Ca.to_quaternion(), w).to_matrix().to_4x4()
    C.translation = Ck.translation.lerp(Ca.translation, w)
    # forward arc between hold and aim: a straight line went through the chest
    C.translation += FWD * AIM.get("transition_arc", 0.0) * 4 * w * (1 - w)
    return C


def smooth(OFF):
    if A.frames: return {f: list(OFF[f]) for f in frames}
    return smooth_runs(OFF, frames, pinned, loop=bool(TWIN))   # not across the start or end of the armpit rest


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
    U = []
    for f in frames:
        u = np.full(len(st), 1e9)
        for c, r, p in solve_arm(side, f, CP[f], TR[f], rolls, poles, all_=True): u[ix[(r, p)]] = c
        # the setup of the approved pose on a key frame, else the one the prop pose was measured with on the real skin
        fx = KEYARMS.get(TWIN.get(f, f), {}).get(side) or (ARMS_FIX[f][side] if f in ARMS_FIX else None)
        if fx in ix:
            k_ = ix[fx]; u_ = u[k_]; u[:] = 1e9; u[k_] = u_
        U.append(u)
    lp = bool(TWIN) and not A.frames; n_ = len(frames)   # the clip ends in its first frame: one setup on both, neighbours over the seam
    pth = [st[i] for i in best_path(U, trans, lp)]
    if A.frames: return dict(zip(frames, pth))
    at = lambda j: j if 0 <= j < n_ else ((j + n_ - 1 if j < 0 else j - n_ + 1) if lp else None)
    sm = {}
    for i, f in enumerate(frames):
        w = [(1 - abs(j - i) / 4, pth[at(j)]) for j in range(i - 3, i + 4) if at(j) is not None]
        sm[f] = tuple(sum(ww * v[q] for ww, v in w) / sum(ww for ww, _ in w) for q in (0, 1))
    return sm


def place(f, C4, prevs, tr):
    sc.frame_set(f)
    for b_ in arm.pose.bones:
        if b_.name.startswith(FINGER_PREFIX) or b_.name in FING_NAMES: b_.rotation_quaternion = (1, 0, 0, 0); b_.location = (0, 0, 0)
    bpy.context.view_layer.update()
    set_prop(C4, f); out = {}
    for side in ("Right", "Left"):
        if side in HELD.get(f, ()):   # --keep-prop: the key pose's own arm holds the prop
            for n in ("upper_arm", "forearm", "hand"): keyb(BN[side][n], f)
            out[side] = dict(kept=True, collisions=0); continue
        r, p = prevs[side][f]; b = solve_arm(side, f, C4, tr, [r], [p])
        setw(BN[side]["upper_arm"], b["q1"].to_matrix() @ K[f][side + "Rua"]); setw(BN[side]["forearm"], b["Rfa3"]); setw(BN[side]["hand"], b["Rh"])
        for n in ("upper_arm", "forearm", "hand"): keyb(BN[side][n], f)
        out[side] = dict(roll=b["roll"], elbow=b["pa"], bend=round(b["bend"], 1), twist=round(b["twist"], 1), collisions=b["coll"])
    wrap_fingers(C4)
    for chains in FING.values():
        for _, names, _ in chains:
            for n in names: keyb(n, f, loc=True)
    return out


# own skeleton: a finger bone whose skin ends up in the prop after the wrap gets its skin radius raised by that depth and
# the hand is wrapped again (the radius stays raised for the frames after it). The median radius missed the thick side of
# Kusznik's thumb metacarpal (2.1 cm): its skin sat 2.9 cm in the fore-end (fingers_in_prop, limit 0.8 cm) -> 0.9 cm.
# Moving the palm out instead did not help (the hand's skin met the bow mount) and lifted the fingertips 6.5 cm off
_FV = np.array([i for i, d_ in enumerate(dom) if d_ in BONE_R])
FING_LIM = METRICS["fingers_in_prop"][0] * HT / REF_HEIGHT


def finger_depths(C4):
    """{own finger bone: deepest skin inside the prop [m]} on the current pose."""
    co = vertices(body, bpy.context.evaluated_depsgraph_get()); Ci = C4.inverted(); out = {}
    for i in _FV:
        q = Ci @ Vector(co[i]); loc, nor, _, dd = PBVH.find_nearest(q, 0.1)
        if loc is not None and dd > out.get(dom[i], 0.0) and (q - loc).dot(nor) < 0 and inside(PBVH, q): out[dom[i]] = dd
    return out


def place_out(f, C4, prevs, tr):
    """place() and up to two more wraps with the radius of every finger bone found in the prop raised by its depth."""
    out = place(f, C4, prevs, tr)
    for _ in range(2 if len(_FV) else 0):
        over = {n: d_ for n, d_ in finger_depths(C4).items() if d_ > 0.5 * FING_LIM}
        if not over: break
        for n, d_ in over.items(): BONE_R[n] += d_
        print("fr. %d: finger skin in the prop, radius raised [cm]: %s" % (f, {n: round(100 * d_, 1) for n, d_ in over.items()}))
        out = place(f, C4, prevs, tr)
    return out


# ---------- face skew guard (the audit's face_skew) ----------
# a head turned about its own axis against the chest drags the face skin that is bound partly to the chest (the own
# rig's face: head weight 0.3-0.9, the rest on the top spine bone) to one side. Kusznik round 8: the key pose's head turned
# 20 deg, the jaw and mouth went 6.2 cm sideways (author: "the face is skewed again"; they fixed their own pose with the
# head and neck: 7 deg, 2.0 cm). Here a face over the audit's limit has its head turned back about its own axis, 2 deg at a
# time, down to half the limit (0.8 of it left 2.6 cm, 13 deg). A face under the limit keeps its turn (m1 Mixamo: 1.8 cm)
HEADB = PROF.bone("head"); FACE_I = None
if not A.keep_prop and HEADB in body.vertex_groups:
    _gi = body.vertex_groups[HEADB].index; _hw = np.zeros(len(body.data.vertices))
    for _v in body.data.vertices:
        for _g in _v.groups:
            if _g.group == _gi: _hw[_v.index] = _g.weight
    FACE_I = np.where((_hw >= 0.3) & (_hw < 0.9))[0]
    FACE_REST = np.array([tuple(body.matrix_world @ body.data.vertices[i].co) for i in FACE_I])
    _ax = AW @ bone(BN["Left"]["upper_arm"]).head_local - AW @ bone(BN["Right"]["upper_arm"]).head_local; FACE_AX = np.array(_ax.normalized())
    FACE_LIM = METRICS["face_skew"][0] * HT / REF_HEIGHT
    if len(FACE_I) < 20: FACE_I = None


def face_skew():
    co = vertices(body, bpy.context.evaluated_depsgraph_get())[FACE_I]
    Hd = np.array((AW @ pb(HEADB).matrix @ bone(HEADB).matrix_local.inverted() @ AW.inverted()).inverted())
    return float(((co @ Hd[:3, :3].T + Hd[:3, 3] - FACE_REST) @ FACE_AX).mean())


def head_twist():
    """The head's turn about its own axis against the top spine bone, from the rest relation [deg]."""
    ch = PROF.spine[-1]; R = (wrot(ch) @ rest_rot(ch).transposed() @ rest_rot(HEADB)).transposed() @ wrot(HEADB)
    q = R.to_quaternion(); return math.degrees(2 * math.atan2(q.y, q.w))


# pass 1: body volume with AI arms; later passes: volume after IK, offset counted from the base pose (not accumulated)
TIME = {}


def stopwatch(what, t0):
    TIME[what] = TIME.get(what, 0.0) + time.perf_counter() - t0; return time.perf_counter()


# the face guard runs before the prop is placed: the head's turn moves skin the hands are then placed against. Run on
# the placed pose it turned Kusznik's head 40 deg back on the recoil frames and the audit found the right hand 9.5 cm in
# the torso where the search had measured 1 cm (the only bone that differed between the solved scene and the file)
for f in (frames if FACE_I is not None else []):
    sc.frame_set(f); sk0 = sk = face_skew(); tw0 = tw = head_twist(); n_ = 0
    while abs(sk) > (0.5 * FACE_LIM if abs(sk0) > FACE_LIM else FACE_LIM) and abs(tw) > 2 and n_ < 20:
        setw(HEADB, wrot(HEADB) @ Quaternion(Vector((0, 1, 0)), -math.copysign(math.radians(2), tw)).to_matrix())
        sk, tw, n_ = face_skew(), head_twist(), n_ + 1
    if n_:
        keyb(HEADB, f)
        print("fr. %d: face skew %.1f -> %.1f cm, head turned back %+.0f -> %+.0f deg" % (f, 100 * abs(sk0), 100 * abs(sk), tw0, tw))
t0 = time.perf_counter()
TR = {f: trees(f) for f in frames}; t0 = stopwatch("trees", t0)
# --keep-prop: the author's key pose holds the prop (Kusznik's armpit aim, set by hand with the stock 13 cm further back
# than the search put it): no prop search, one placement of the arms and fingers
BASE = {f: (K[f]["prop"], W_AIM[f]) if A.keep_prop else base_pose(f) for f in frames}; t0 = stopwatch("base pose", t0)
OFF = {f: [0.0] * NX for f in frames}; SEARCHED = {}; SM = {}; LIMBD = {}
# --keep-prop: a hand whose palm lies on the stock (within the stock's radius + clearance + the audit's hand_to_prop of its
# axis) keeps its arm and hand as the key pose has them, only its fingers are wrapped; a hand off the prop takes the
# motion's grip. Kusznik, author's aim: refitted to the motion's grip (even from the key pose's own place and direction
# on the stock) the hands moved 2-6 cm and turned 28-39 deg, the left wrist twist 75 -> 101 deg
for f in (frames if A.keep_prop else []):
    sc.frame_set(f); _Ci = K[f]["prop"].inverted(); _off = {s_: (_Ci @ K[f][s_ + "palm"]) for s_ in ("Left", "Right")}
    HELD[f] = {s_ for s_, p_ in _off.items()
               if p_.yz.length <= r_at(p_.x) + GP["clearance"] + METRICS["hand_to_prop_" + s_[0]][0] * HT / REF_HEIGHT}
    print("keep prop fr. %d: palm off the stock axis %s cm, arms kept: %s" % (
        f, {s_: round(100 * p_.yz.length, 1) for s_, p_ in _off.items()}, sorted(HELD[f]) or "-"))
todo = frames; KEYS = sorted(KEYP)
# the first key pose also ends the clip: the last frame starts from the first frame's answer (solved from its own
# neighbour, the hands turned 10 deg over the loop seam where they turned 3.5 before)
TWIN = {all_frames[-1]: all_frames[0]} if all_frames[0] in KEYP and len(all_frames) > 1 else {}
for it in range(GP.get("passes", 4)):
    PASS[0] = it
    # with approved key poses the clip is solved outwards from them, each frame starting from its neighbour's answer; in
    # later passes from its own smoothed one. Solved alone, neighbours took unrelated answers of nearly the same cost
    # (Kusznik: stock pitch +30, +11, -1, -13 deg on frames 56, 58, 60, 64) and their average was nobody's
    near = lambda f: nearest(f, KEYS + list(TWIN))
    seq = sorted(todo, key=lambda f: (abs(f - near(f)), f)) if KEYS and not it else todo; solved = set()
    for f in ([] if A.keep_prop else seq):
        # the same skin and bones as when this frame was last searched: the search would repeat itself step for step
        if SEARCHED.get(f) == SIG[f]: COUNT["kept"] += 1; solved.add(f); continue
        seed = SM[f] if KEYS and it else None; like = None
        if KEYS and not it:
            g = TWIN.get(f, f + (near(f) > f) - (near(f) < f))
            if g in solved and pinned(g) == pinned(f):
                seed = OFF[g]; like = (ARMS_FIX[g][BUTT_SIDE][1] if pinned(g) and g in ARMS_FIX else None, COSTF[g]) if g in COSTF else None
        ON_FRAME[0] = None; C2_, OFF[f] = search(BASE[f][0], f, TR[f], seed, like); ON_FRAME[0] = None; SEARCHED[f] = SIG[f]; solved.add(f)
        if A.frames and any(OFF[f]):
            print("fr. %d: the answer (%s) costs %.1f: %s" % (f, " ".join("%.3g" % v for v in OFF[f]), COSTF.get(f, 0.0), cost_parts(C2_, f, TR[f])))
            ON_FRAME[0] = None
    t0 = stopwatch("search", t0)
    SM = smooth(OFF)
    CP = {f: shift(BASE[f][0], SM[f], f) for f in frames}
    prevs = {s: path(s, CP, TR) for s in ("Left", "Right")}; PREV_F.clear(); t0 = stopwatch("path", t0)
    WR = {f: place_out(f, CP[f], prevs, TR[f]) for f in frames}; t0 = stopwatch("place (IK + fingers)", t0)
    TR = {f: trees(f) for f in frames}; t0 = stopwatch("trees", t0)
    if ARM_COLL:   # the placed pose's hands and forearms in the head and torso, as the audit measures them
        for f in frames: sc.frame_set(f); LIMBD[f] = limbs_excess(vertices(body, bpy.context.evaluated_depsgraph_get()))[0]
        if A.frames: print("placed, limbs past their limits [cm]:", {f: round(100 * LIMBD[f], 1) for f in frames})
    todo = [f for f in frames if prop_hits(CP[f], TR[f], pinned(f)) or any(WR[f][s]["collisions"] for s in WR[f])
            or (ARM_COLL and body_check(f, CP[f])[0] > BODY_LIM)]; t0 = stopwatch("check", t0)
    print("pass", it + 1, "frames with collision:", len(todo), todo[:25])
    if not todo or A.keep_prop: break
print("time [s]:", ", ".join("%s %.1f" % kv for kv in TIME.items()))
print("time, search: %d prop poses asked for, %d measured on the skin, %d known from the same search, %d frames kept from the pass before" % (
    COUNT["asked"], COUNT["skin"], COUNT["known"], COUNT["kept"]))
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
if TGT:   # how often the clip shows the prop where the approved pose has it
    _o = sorted(f for f in TGT if TGT[f][-1] == "other pocket"); _l = sum(TGT[f][-1] == "as the frame next to it" for f in TGT)
    _k = sum(len(TGT[f]) == 1 for f in TGT)
    print("APPROVED PLACE: kept as it is on %d frames, held as the frame next to it on %d, searched near it on %d, another pocket on %d %s" % (
        _k, _l, len(TGT) - _k - _l - len(_o), len(_o), _o[:25] or ""))
    for k_ in sorted(KEYP):
        if k_ in SM: print("APPROVED PLACE fr. %d: the prop ends %.1f cm and %.0f deg from it" % (
            k_, 100 * math.sqrt(sum(v * v for v in SM[k_][:3])), max(abs(v) for v in SM[k_][3:])))
for f in frames: WR[f]["offset"] = [round(v, 4) for v in SM[f]]
for f in frames:
    if f not in BODYD: body_check(f, CP[f])
fb = max(frames, key=lambda f: BODYD[f][0])
if UNDER: print("POCKET:", {f: POCKET_INFO.get(f, "-") for f in frames if pinned(f)})
print("PROP IN BODY: max %.1f cm (fr. %d, %s), limit %.1f cm, frames over it %d" % (
    100 * BODYD[fb][0], fb, BODYD[fb][1] or "-", 100 * BODY_LIM, sum(BODYD[f][0] > BODY_LIM for f in frames)))
if LIMBD:
    fl = max(frames, key=lambda f: LIMBD[f]); _ov = [f for f in frames if LIMBD[f] > 0]
    print("LIMBS IN BODY: hands and forearms past their limits in the head and torso, max %.1f cm (fr. %d), frames over %d %s" % (
        100 * LIMBD[fl], fl, len(_ov), _ov[:25] or ""))

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

# per frame: arm setups, prop offset and the aim weight (the audit checks the armpit pocket on aim frames)
json.dump({str(f): dict(v, aim=round(W_AIM[f], 3)) for f, v in WR.items()}, open(A.out.replace(".glb", "_arms.json"), "w"), indent=0)
bpy.ops.export_scene.gltf(filepath=A.out, export_format="GLB", export_animations=True)
print("OK", A.out)
