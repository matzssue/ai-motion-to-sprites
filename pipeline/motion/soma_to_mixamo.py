"""Kimodo BVH (SOMA77 skeleton, T-pose) -> action on the rig (FBX, or GLB from prepare_rig), exported as a GLB clip
for merge_actions. Bones are matched by role (skeletons/soma.json -> the rig's skeleton profile, default mixamo).
Rest-pose correction (CORR): the auto-rig stands in an A-pose; without it the arms go sideways.
blender -b --python pipeline/motion/soma_to_mixamo.py -- src.bvh rig.(fbx|glb) out.glb action_name [loop_blend_s] [--skeleton X]
loop_blend_s > 0: the last N s blend smoothly back to the frame-0 pose (Kimodo does not return: a head popped 26 deg at the loop seam)."""
import bpy, sys, os, math
from mathutils import Matrix, Quaternion, Vector
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import skeleton
from own_skeleton import palm_normal, finger_key

a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
a, SKEL = skeleton.take_arg(a)
if len(a) < 4 or a[0] in ("-h", "--help"):
    print(__doc__); raise SystemExit(0 if a[:1] in (["-h"], ["--help"]) else 2)
bvh, rig, out, act_name = a[0], a[1], a[2], a[3]
LOOP = float(a[4]) if len(a) > 4 else 0.0

bpy.ops.wm.read_factory_settings(use_empty=True)
if rig.lower().endswith(".fbx"): bpy.ops.import_scene.fbx(filepath=rig)
else: bpy.ops.import_scene.gltf(filepath=rig)
tgt = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for ob in list(bpy.data.objects):
    if ob.type == "MESH":
        for m in ob.material_slots:
            m.material = None
if tgt.animation_data:
    tgt.animation_data.action = None
bpy.ops.import_anim.bvh(filepath=bvh, rotate_mode="QUATERNION", axis_forward="-Z", axis_up="Y", update_scene_fps=True)
src = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o is not tgt)
SRC = skeleton.load("soma")
TGT = skeleton.for_rig(SKEL, {b.name: b.parent.name if b.parent else None for b in tgt.data.bones}).prof
MAP = dict(SRC.pairs(TGT))   # source bone -> target bone (full names)
SH, TH = SRC.bone("hips"), TGT.bone("hips")
sc = bpy.context.scene
f0, f1 = (int(v) for v in src.animation_data.action.frame_range)


def wrot(ob, name, rest=False):
    if rest:
        m = ob.matrix_world @ ob.data.bones[name].matrix_local
    else:
        m = ob.matrix_world @ ob.pose.bones[name].matrix
    return m.to_3x3().normalized().to_quaternion()


def whead(ob, name, rest=False):
    m = ob.data.bones[name].matrix_local if rest else ob.pose.bones[name].matrix
    return ob.matrix_world @ m.translation


def wtip(ob, name, aim, rest=False):
    """Where the bone points: head of the next bone along the body, or its own tail when the profile has none."""
    if aim: return whead(ob, aim, rest)
    return ob.matrix_world @ (ob.data.bones[name].tail_local if rest else ob.pose.bones[name].tail)


# Direction alignment: "left" and "up" axes from the rest pose of both skeletons.
def basis(ob, S):
    x = (whead(ob, S.bone("upper_arm", "L"), True) - whead(ob, S.bone("upper_arm", "R"), True)).normalized()
    z = (whead(ob, S.bone("neck"), True) - whead(ob, S.bone("hips"), True))
    z = (z - x * z.dot(x)).normalized()
    return Matrix((x, z.cross(x), z)).transposed()


Bs = basis(src, SRC)
Bt = basis(tgt, TGT)
C = (Bt @ Bs.inverted()).to_quaternion()
hs = whead(src, SH, True).z - min(whead(src, n, True).z for n in SRC.bones("foot"))
ht = whead(tgt, TH, True).z - min(whead(tgt, n, True).z for n in TGT.bones("foot"))
k = ht / hs
print("C angle %.1f deg, scale %.3f" % (math.degrees(C.angle), k))

SCH = {s_: SRC.aim(s_) for s_ in MAP}
TCH = {t_: TGT.aim(t_) for t_ in MAP.values()}


def sdir(s, rest=False):
    return (wtip(src, s, SCH[s], rest) - whead(src, s, rest)).normalized()


def tdir(t, rest=False):
    return (wtip(tgt, t, TCH[t], rest) - whead(tgt, t, rest)).normalized()


# Rest-pose correction: the target is first put into the source rest pose (A-pose vs T-pose).
CORR = {}
for s_, t_ in MAP.items():
    CORR[t_] = Quaternion() if s_ == SH else tdir(t_, True).rotation_difference(C @ sdir(s_, True))
    print("rest %-14s %5.1f deg" % (TGT.short(t_), math.degrees(CORR[t_].angle)))


# ---------- fingers: the bend of every finger joint towards its palm, measured from joint positions (the two skeletons'
# rest frames do not matter) and put on the same joint of the rig as a change from each skeleton's rest. Only fingers both
# profiles list in `finger_chains` (the own skeleton; a Mixamo template's finger bones own no skin and get nothing).
def kids_head(ob, n, rest):
    b = ob.data.bones[n]
    return whead(ob, b.children[0].name, rest) if b.children else wtip(ob, n, None, rest)


def hand_points(ob, S, side, rest):
    """(wrist, {finger: [joint positions: knuckle .. tip]}, palm normal) of one hand; the knuckle = head of the
    third bone from the end of the chain (a metacarpal before it is skipped)."""
    ch = S.finger_chains(side); w = whead(ob, S.bone("hand", side), rest)
    J = {f: [whead(ob, n, rest) for n in c[-3:]] + [kids_head(ob, c[-1], rest)] for f, c in ch.items()}
    pre = {f: (whead(ob, c[-4], rest) if len(c) > 3 else None) for f, c in ch.items()}
    jt = {side + "Hand": tuple(w)}; jt.update({finger_key(side, f, 1): tuple(J[f][0]) for f in J})
    n = palm_normal(jt, side)
    return w, J, pre, (Vector(tuple(n)) if n is not None else None)


def bends(ob, S, side, rest):
    """{finger: [bend of bone 1, 2, 3 towards the palm, rad]}: angle of each bone against the one before it (the metacarpal,
    or the hand axis for a finger without one) in the plane of that bone and the palm normal."""
    w, J, pre, n = hand_points(ob, S, side, rest); axis = (J["middle"][0] - w).normalized(); out = {}
    for f, P in J.items():
        prev = (P[0] - pre[f]).normalized() if pre[f] is not None else axis; b = []
        for i in range(3):
            d = (P[i + 1] - P[i]).normalized(); u = n - prev * n.dot(prev)
            b.append(math.atan2(d.dot(u.normalized()), d.dot(prev)) if u.length > 1e-6 else 0.0); prev = d
        out[f] = b
    return out


FSIDES = [s_ for s_ in skeleton.SIDES if {"index", "middle", "pinky"} <= set(SRC.finger_chains(s_)) & set(TGT.finger_chains(s_))]
FAX, FREST = {}, {}
for s_ in FSIDES:
    w_, J_, _, n_ = hand_points(tgt, TGT, s_, True)
    FREST[s_] = bends(src, SRC, s_, True)
    for f_, c_ in TGT.finger_chains(s_).items():
        if f_ not in SRC.finger_chains(s_): continue
        for i, bn in enumerate(c_[-3:]):
            d_ = (J_[f_][i + 1] - J_[f_][i]).normalized()
            R_ = (tgt.matrix_world @ tgt.data.bones[bn].matrix_local).to_3x3().normalized()
            FAX[bn] = (s_, f_, i, (R_.transposed() @ d_.cross(n_)).normalized())   # + about it = towards the palm
print("fingers: %s" % ("%d bones from the source's finger bends (%s)" % (len(FAX), ", ".join(FSIDES)) if FAX
                       else "not carried (the profiles share no finger_chains)"))
FBEND = {}
ERR = {}
src_rest = {s: wrot(src, s, True) for s in MAP}
tgt_rest = {t: wrot(tgt, t, True) for t in MAP.values()}
hips_rest_s, hips_rest_t = whead(src, SH, True), whead(tgt, TH, True)
order = sorted(MAP, key=lambda s: len(tgt.pose.bones[MAP[s]].parent_recursive))
for pb in tgt.pose.bones:
    pb.rotation_mode = "QUATERNION"
act = bpy.data.actions.new(act_name)
tgt.animation_data_create()
tgt.animation_data.action = act
inv_obj = tgt.matrix_world.to_3x3().normalized().to_quaternion().inverted()
for f in range(f0, f1 + 1):
    sc.frame_set(f)
    bpy.context.view_layer.update()
    for s in order:
        t = MAP[s]
        pb = tgt.pose.bones[t]
        wr = C @ wrot(src, s) @ src_rest[s].inverted() @ C.inverted() @ CORR[t] @ tgt_rest[t]
        m = (inv_obj @ wr).to_matrix().to_4x4()
        m.translation = pb.matrix.translation
        if s == SH:
            d = C @ (whead(src, SH) - hips_rest_s) * k
            m.translation = tgt.matrix_world.inverted() @ (hips_rest_t + d)
        pb.matrix = m
        if pb.parent is not None:
            pb.location = (0, 0, 0)
        bpy.context.view_layer.update()
    for s_, t_ in MAP.items():
        if s_ != SH:
            ang = math.degrees((C @ sdir(s_)).angle(tdir(t_)))
            ERR[TGT.short(t_)] = max(ERR.get(TGT.short(t_), 0), ang)
    if FAX:
        B_ = {s_: bends(src, SRC, s_, False) for s_ in FSIDES}
        for bn, (s_, f_, i, ax) in FAX.items():
            a_ = B_[s_][f_][i] - FREST[s_][f_][i]; FBEND[bn] = max(FBEND.get(bn, 0), abs(math.degrees(a_)))
            pb = tgt.pose.bones[bn]; pb.rotation_quaternion = Quaternion(ax, a_); pb.keyframe_insert("rotation_quaternion", frame=f - f0)
    for t in MAP.values():
        pb = tgt.pose.bones[t]
        pb.keyframe_insert("location", frame=f - f0)
        pb.keyframe_insert("rotation_quaternion", frame=f - f0)
        pb.keyframe_insert("scale", frame=f - f0)
print("MAX DIRECTION ERROR [deg]:", {k: round(v, 1) for k, v in ERR.items()})
if FBEND: print("fingers: max bend from rest [deg]:", {TGT.short(k): round(v, 1) for k, v in sorted(FBEND.items())})
bpy.data.objects.remove(src)
for ac in list(bpy.data.actions):
    if ac is not act:
        bpy.data.actions.remove(ac)
if LOOP > 0:
    # loop closure: rotation of every bone (and root location) in the last N frames -> frame-0 pose
    N = max(2, int(round(LOOP * sc.render.fps))); last = f1 - f0
    curves = {}
    for fc in (act.fcurves if hasattr(act, "fcurves") else [c for l in act.layers for st in l.strips for b in st.channelbags for c in b.fcurves]):
        curves.setdefault(fc.data_path, {})[fc.array_index] = fc
    for path, axes in curves.items():
        if path.endswith("rotation_quaternion") and len(axes) == 4:
            q0 = Quaternion([axes[i].evaluate(0) for i in range(4)])
            for k in range(N + 1):
                fr = last - N + k; w = k / N; w = w * w * (3 - 2 * w)
                q = Quaternion([axes[i].evaluate(fr) for i in range(4)])
                if q.dot(q0) < 0: q = -q
                qn = q.slerp(q0, w)
                for i in range(4): axes[i].keyframe_points.insert(fr, qn[i], options={"REPLACE"})
        elif path.endswith("location") and path.startswith('pose.bones["%s"]' % TH):
            for i, fc in axes.items():
                v0 = fc.evaluate(0)
                for k in range(N + 1):
                    fr = last - N + k; w = k / N; w = w * w * (3 - 2 * w)
                    fc.keyframe_points.insert(fr, fc.evaluate(fr) * (1 - w) + v0 * w, options={"REPLACE"})
    print("loop: last %d frames -> frame 0" % N)
act.frame_range = (0, f1 - f0)
sc.frame_start, sc.frame_end = 0, f1 - f0
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_animations=True, export_frame_range=True,
                          export_apply=False, export_materials="NONE", export_image_format="NONE")
print("RETARGET OK", out, f1 - f0 + 1, "frames, fps", sc.render.fps)
