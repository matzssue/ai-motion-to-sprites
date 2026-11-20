"""Blender half of the auto-rig (`auto_rig.py`): mesh export and rig build.
blender -b --python pipeline/rig/auto_rig_blender.py -- export --src=<x>_for_rig.fbx --out=<x>.npz
blender -b --python pipeline/rig/auto_rig_blender.py -- build --src=... --joints=<x>.json [--template=<mixamo skeleton>.fbx] --out=rig_base.fbx
    [--no-fingers]
Without --template the own skeleton (pipeline/lib/own_skeleton.py) is built from the joints and checked on a fist pose."""
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import own_skeleton  # noqa: E402


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); raise SystemExit(0)
    out = {"stage": argv[0]}
    for item in argv[1:]:
        key, _, value = item.lstrip("-").partition("=")
        out[key] = value if value else True
    return out


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=os.path.abspath(path))
    return [o for o in bpy.data.objects if o not in before]


def mesh_arrays(meshes):
    verts, tris, offset = [], [], 0
    for obj in meshes:
        data = obj.data
        data.calc_loop_triangles()
        co = np.array([obj.matrix_world @ v.co for v in data.vertices], dtype=np.float64)
        tri = np.array([t.vertices[:] for t in data.loop_triangles], dtype=np.int64)
        verts.append(co); tris.append(tri + offset); offset += len(co)
    return np.concatenate(verts), np.concatenate(tris)


def stage_export(a):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    meshes = [o for o in import_fbx(a["src"]) if o.type == "MESH"]
    verts, tris = mesh_arrays(meshes)
    np.savez(a["out"], verts=verts, tris=tris)
    print("auto_rig: exported %d vertices, %d triangles" % (len(verts), len(tris)))


P = "mixamorig:"
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
# bone -> bone giving its direction (chain ends: own tail of the template)
AIM = {"Hips": "Spine", "Spine": "Spine1", "Spine1": "Spine2", "Spine2": "Neck", "Neck": "Head", "Head": "HeadTop_End"}
for s in ("Left", "Right"):
    AIM.update({s + "Shoulder": s + "Arm", s + "Arm": s + "ForeArm", s + "ForeArm": s + "Hand",
                s + "Hand": s + "HandMiddle1", s + "UpLeg": s + "Leg", s + "Leg": s + "Foot",
                s + "Foot": s + "ToeBase", s + "ToeBase": s + "Toe_End"})
    for f in FINGERS:
        for i in (1, 2, 3):
            AIM[s + "Hand%s%d" % (f, i)] = s + "Hand%s%d" % (f, i + 1)

# On 18 Mixamo rigs these bones have orientation IDENTICAL to the clip dummy (0.0 deg), whatever the character's lean.
# Rotating them after the child direction tilted the whole body in animation (37 deg).
CANONICAL = {"Hips", "Neck", "Head", "HeadTop_End"}


def rotation_between(a, b):
    return a.normalized().rotation_difference(b.normalized()).to_matrix()


def finger_targets(arm_obj, joints_local):
    """Template fingers moved onto the new hand: hand rotation + hand length scale."""
    out = {}
    bones = arm_obj.data.bones
    for s in ("Left", "Right"):
        hand0 = bones[P + s + "Hand"].head_local.copy()
        mid0 = bones[P + s + "HandMiddle4"].tail_local.copy()
        hand1 = joints_local[s + "Hand"]
        tip1 = joints_local[s + "Tip"]
        rot = rotation_between(mid0 - hand0, tip1 - hand1)
        scale = (tip1 - hand1).length / max((mid0 - hand0).length, 1e-6)
        for b in bones:
            short = b.name[len(P):]
            if short.startswith(s + "Hand") and short != s + "Hand":
                out[short] = hand1 + rot @ ((b.head_local - hand0) * scale)
        out[s + "HandScale"] = scale
    return out


def fill_empty_weights(obj, k=6):
    """Bone heat leaves loose bits of mesh without weights (2.9% of one model): such a vertex stays put while the rest moves.
    It gets the weights of its nearest weighted neighbours (inverse-distance mean)."""
    from mathutils import kdtree
    verts = obj.data.vertices
    names = {g.index: g.name for g in obj.vertex_groups}
    weights = [{names[g.group]: g.weight for g in v.groups if g.weight > 1e-4} for v in verts]
    done = [i for i, w in enumerate(weights) if w]
    empty = [i for i, w in enumerate(weights) if not w]
    print("auto_rig: weights - without a bone after bone heat: %d of %d (%.2f%%)" % (len(empty), len(verts), 100.0 * len(empty) / len(verts)))
    if not empty or not done:
        return
    tree = kdtree.KDTree(len(done))
    for i in done:
        tree.insert(verts[i].co, i)
    tree.balance()
    groups = {g.name: g for g in obj.vertex_groups}
    for i in empty:
        acc = {}
        for co, idx, dist in tree.find_n(verts[i].co, k):
            w = 1.0 / max(dist, 1e-5)
            for name, val in weights[idx].items():
                acc[name] = acc.get(name, 0.0) + w * val
        total = sum(acc.values())
        for name, val in acc.items():
            groups[name].add([i], val / total, "REPLACE")


def make_proxy(meshes, voxel_frac):
    """Watertight copy of the mesh (voxel remesh). A generator model is hundreds of loose shells with holes; bone heat on it
    gives ragged weights and the mesh TEARS in motion. On a closed volume heat works."""
    bpy.ops.object.select_all(action="DESELECT")
    copies = []
    for o in meshes:
        c = o.copy(); c.data = o.data.copy(); c.modifiers.clear()
        bpy.context.scene.collection.objects.link(c); copies.append(c)
    for c in copies:
        c.select_set(True)
    bpy.context.view_layer.objects.active = copies[0]
    if len(copies) > 1:
        bpy.ops.object.join()
    proxy = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    height = max(v.co.z for v in proxy.data.vertices) - min(v.co.z for v in proxy.data.vertices)
    mod = proxy.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"; mod.voxel_size = voxel_frac * height
    bpy.ops.object.modifier_apply(modifier=mod.name)
    for g in list(proxy.vertex_groups):
        proxy.vertex_groups.remove(g)
    print("auto_rig: voxel proxy %.3f m -> %d vertices" % (voxel_frac * height, len(proxy.data.vertices)))
    return proxy


def transfer_weights(src, dst, k=4):
    """Weights from the proxy to the original: mean of the k nearest proxy vertices."""
    from mathutils import kdtree
    sv = src.data.vertices
    names = {g.index: g.name for g in src.vertex_groups}
    sw = [{names[g.group]: g.weight for g in v.groups if g.weight > 1e-4} for v in sv]
    tree = kdtree.KDTree(len(sv))
    for i, v in enumerate(sv):
        tree.insert(src.matrix_world @ v.co, i)
    tree.balance()
    for g in list(dst.vertex_groups):
        dst.vertex_groups.remove(g)
    groups = {g.name: dst.vertex_groups.new(name=g.name) for g in src.vertex_groups}
    for v in dst.data.vertices:
        acc = {}
        for co, idx, dist in tree.find_n(dst.matrix_world @ v.co, k):
            w = 1.0 / max(dist, 1e-5)
            for name, val in sw[idx].items():
                acc[name] = acc.get(name, 0.0) + w * val
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
        total = sum(val for _, val in top) or 1.0
        for name, val in top:
            groups[name].add([v.index], val / total, "REPLACE")


def heat_weights(arm, proxy, factor):
    """ARMATURE_AUTO at a magnified scale; returns the fraction of vertices without weights."""
    proxy.parent = None
    proxy.modifiers.clear()
    for g in list(proxy.vertex_groups):
        proxy.vertex_groups.remove(g)
    proxy.matrix_world = Matrix.Identity(4)
    arm.scale *= factor
    proxy.scale = (factor, factor, factor)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True); arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    arm.scale /= factor
    bpy.context.view_layer.update()
    groups = {g.index for g in proxy.vertex_groups}
    empty = sum(1 for v in proxy.data.vertices if not any(g.group in groups and g.weight > 1e-4 for g in v.groups))
    return empty / max(len(proxy.data.vertices), 1)


def distance_weights(arm, proxy, power=4.0, top=3):
    """Last resort: weight ~ 1/distance^4 from the bone segment (3 nearest)."""
    print("auto_rig: WARNING - weights from distance to bones (bone heat failed)")
    segs = [(b.name, arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local) for b in arm.data.bones if b.use_deform]
    groups = {n: (proxy.vertex_groups.get(n) or proxy.vertex_groups.new(name=n)) for n, _, _ in segs}
    for v in proxy.data.vertices:
        p = proxy.matrix_world @ v.co
        ds = []
        for n, h, t in segs:
            d = t - h
            u = max(0.0, min(1.0, (p - h).dot(d) / max(d.length_squared, 1e-9)))
            ds.append(((p - (h + u * d)).length, n))
        ds.sort()
        ws = [(n, 1.0 / max(dist, 1e-4) ** power) for dist, n in ds[:top]]
        total = sum(w for _, w in ws)
        for n, w in ws:
            groups[n].add([v.index], w / total, "REPLACE")


def stage_build(a):
    if not a.get("template"):
        return build_own(a)
    joints = json.load(open(a["joints"]))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    tmpl = import_fbx(a["template"])
    arm = next(o for o in tmpl if o.type == "ARMATURE")
    for o in tmpl:
        if o.type != "ARMATURE":
            bpy.data.objects.remove(o, do_unlink=True)
    arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    inv = arm.matrix_world.inverted()
    local = {k: inv @ Vector(v) for k, v in joints.items()}
    local.update({k: v for k, v in finger_targets(arm, local).items() if not k.endswith("Scale")})
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for b in eb:
        b.use_connect = False
    old = {b.name[len(P):]: (b.head.copy(), b.tail.copy(), b.matrix.copy()) for b in eb}
    for short, (h0, t0, m0) in old.items():
        if short not in local:
            raise SystemExit("auto_rig: joint %s missing in %s" % (short, a["joints"]))
        h1 = local[short]
        aim = AIM.get(short)
        if aim and aim in local:
            d0, d1 = old[aim][0] - h0, local[aim] - h1
        else:  # end of chain: parent direction, length at the parent's scale
            parent = eb[P + short].parent.name[len(P):]
            d0 = h0 - old[parent][0]
            d1 = h1 - local[parent]
        rot = rotation_between(d0, d1) if d0.length > 1e-6 and d1.length > 1e-6 else Matrix.Identity(3)
        if short in CANONICAL:
            rot = Matrix.Identity(3)
        scale = d1.length / d0.length if d0.length > 1e-6 else 1.0
        bone = eb[P + short]
        length = max((t0 - h0).length * scale, 0.5)
        m = (rot @ m0.to_3x3()).to_4x4()
        m.translation = h1
        bone.matrix = m
        bone.length = length
    bpy.ops.object.mode_set(mode="OBJECT")
    # the same deforming set as Mixamo (51 of 65: no end bones)
    no_fingers = bool(a.get("no-fingers"))
    for b in arm.data.bones:
        short = b.name[len(P):]
        end = short.endswith("_End") or (any(f in short for f in FINGERS) and short.endswith("4"))
        b.use_deform = not end and not (no_fingers and any(f in short for f in FINGERS))
    skin_and_export(arm, a)


def skin_and_export(arm, a, before_export=None):
    """Weights (bone heat on a voxel proxy, moved onto the original), parenting, FBX export."""
    meshes = [o for o in import_fbx(a["src"]) if o.type == "MESH"]
    proxy = make_proxy(meshes, float(a.get("voxel", "0.008")))
    # bone heat has thresholds in absolute units: a 1.38 m character got "failed to find solution" and ZERO weights,
    # 1.85 m passed. Run at x10; still empty -> x100; finally weights from distance to bones.
    for factor in (10.0, 100.0):
        if heat_weights(arm, proxy, factor) < 0.5:
            break
        print("auto_rig: bone heat at x%g gave no weights" % factor)
    else:
        distance_weights(arm, proxy)
    fill_empty_weights(proxy)
    for o in meshes:
        transfer_weights(proxy, o)
    bpy.data.objects.remove(proxy, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_NAME")  # empty groups already exist; parent + modifier only
    for o in meshes:
        print("auto_rig: %s - groups %d, modifiers %s" % (o.name, len(o.vertex_groups), [m.type for m in o.modifiers]))
    if before_export:
        before_export(arm, meshes)
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    arm.select_set(True)
    bpy.ops.export_scene.fbx(filepath=os.path.abspath(a["out"]), use_selection=True, add_leaf_bones=False, bake_anim=False,
                             path_mode="COPY", embed_textures=True, object_types={"ARMATURE", "MESH"})
    print("auto_rig: saved %s" % a["out"])


def build_own(a):
    """Own skeleton from the joints: bones, rest orientation and roll from own_skeleton.bone_frames, no template."""
    frames = own_skeleton.bone_frames(json.load(open(a["joints"])))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    arm = bpy.data.objects.new(own_skeleton.NAME, bpy.data.armatures.new(own_skeleton.NAME))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones
    for name, parent, *_ in own_skeleton.BONES:
        head, tail, z = frames[name]
        e = eb.new(name)
        e.head, e.tail = Vector(head), Vector(tail)
        e.align_roll(Vector(z))
        if parent:
            e.parent = eb[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    fingers = not a.get("no-fingers")
    for b in arm.data.bones:
        b.use_deform = own_skeleton.deforming(b.name, fingers)
    print("auto_rig: own skeleton '%s' - %d bones, %d deform" % (own_skeleton.NAME, len(arm.data.bones),
                                                                 sum(b.use_deform for b in arm.data.bones)))
    # finger weights: bone heat like the rest. Weights along the chains (nearest chain, blended at joints and knuckles) were
    # measured too and tore more (Kusznik, 30 deg fist: 1.8-2.3% of hand edges over 50% vs 1.2% with heat; a 0.005 voxel: 1.6%)
    skin_and_export(arm, a, (lambda arm_, meshes: (own_weight_rules(arm_, meshes), finger_tubes(arm_, meshes), fist_check(arm_, meshes)))
                    if fingers else own_weight_rules)


# finger weights stay in a tube around their own finger. Bone heat gave the first thumb bone (it starts next to the wrist)
# the cuff, its cloth strips and the palm's heel (Kusznik: 490 vertices, median 3 cm and 90% within 5.5 cm of the thumb;
# a claw is ~1 cm thick): the grip bent them into the crossbow (4 cm). Tube = TUBE x the finger's own thickness (median
# distance of its outer two bones' skin from the chain), fading to the hand by TUBE_FADE x that.
TUBE, TUBE_FADE = 2.0, 3.0
# thin cords inside the tube: Kusznik's wrist wraps hang cords 2-4 cm from the thumb's and pinky's first bones (thickness
# < 6 mm, finger radius 1.2-2.3 cm); weighted to those bones they were pulled up to 4.3 cm by the grip and drawn as strings
# across the crossbow (Mixamo: the same cords are all hand). Mesh thinner than THIN x the finger's radius, outside its skin
# (farther than its radius) and nearest to the finger's first bone goes to the hand. Claws (thin, at the third bone) stay.
THIN = 0.35


def finger_tubes(arm, meshes):
    """Moves finger weight farther from the finger's chain than the tube, and thin cords beside its first bone, onto the
    hand bone; prints what moved."""
    from mathutils.bvhtree import BVHTree
    W = arm.matrix_world
    for o in meshes:
        names = [g.name for g in o.vertex_groups]; gi = {n: i for i, n in enumerate(names)}
        co = np.array([tuple(o.matrix_world @ v.co) for v in o.data.vertices])
        tree = BVHTree.FromPolygons([Vector(c) for c in co], [p.vertices[:] for p in o.data.polygons])
        nor = [(o.matrix_world.to_3x3() @ v.normal).normalized() for v in o.data.vertices]

        def thickness(i):
            hit = tree.ray_cast(Vector(co[i]) - nor[i] * 1e-4, -nor[i], 0.2)
            return hit[3] if hit[0] is not None else 0.2
        wts = [{g.group: g.weight for g in v.groups} for v in o.data.vertices]
        dom = [max(w, key=w.get) if w else -1 for w in wts]; changed = set()
        for s, side in own_skeleton.SIDES:
            hand = gi.get("hand." + s)
            if hand is None: continue
            moved, verts, cords, kept = 0.0, 0, 0, 0
            tips = {gi[b] for f in own_skeleton.FINGERS for b in ("%s.2.%s" % (f, s), "%s.3.%s" % (f, s)) if b in gi}
            for f in own_skeleton.FINGERS:
                bones = ["%s.%d.%s" % (f, i, s) for i in (1, 2, 3)]
                if not all(b in gi and b in arm.data.bones for b in bones): continue
                end = arm.data.bones.get("%s_end.%s" % (f, s))
                P = [np.array(W @ arm.data.bones[b].head_local) for b in bones]
                P.append(np.array(W @ (end.head_local if end else arm.data.bones[bones[-1]].tail_local)))
                d = np.full(len(co), np.inf); seg = np.zeros(len(co), int)
                for k_, (a_, b_) in enumerate(zip(P, P[1:])):
                    ab = b_ - a_; u = np.clip(((co - a_) @ ab) / max(ab @ ab, 1e-12), 0, 1)
                    dk = np.linalg.norm(co - (a_ + u[:, None] * ab), axis=1); seg[dk < d] = k_; d = np.minimum(d, dk)
                g = [gi[b] for b in bones]
                outer = [i for i, x in enumerate(dom) if x in g[1:]]
                if not outer: continue
                r = float(np.median(d[outer]))
                for i, w in enumerate(wts):
                    k = 1.0 if d[i] <= TUBE * r else max(0.0, 1.0 - (d[i] - TUBE * r) / ((TUBE_FADE - TUBE) * r))
                    if not any(x in w for x in g): continue
                    if k > 0.0 and seg[i] == 0 and r < d[i] and thickness(i) < THIN * r: k = 0.0; cords += 1
                    if k >= 1.0: continue
                    m = sum(w.get(x, 0.0) * (1 - k) for x in g)
                    if m < 1e-4: continue
                    for x in g:
                        if x in w: w[x] *= k
                    # on another finger's outer bone the stray weight goes to that bone, not the hand: Kusznik's right
                    # middle claw had a quarter of a neighbour's weight, it went to the hand, the curl pulled the claw
                    # 3.6 cm back and folded its tip over (author: "the green finger's tip is bent oddly"; finger_tip_fold)
                    to = dom[i] if dom[i] in tips and dom[i] not in g else hand
                    w[to] = w.get(to, 0.0) + m; moved += m; verts += 1; changed.add(i); kept += to != hand
            print("auto_rig: finger tubes %s %s - weight moved to the hand on %d vertices (%.0f vertex-weights), %d of them thin cords;"
                  " %d of them on another finger's outer bone kept there" % (o.name, side, verts, moved, cords, kept))
        for i in changed:
            for x, val in wts[i].items():
                o.vertex_groups[x].add([i], val, "REPLACE")


# limb core: the middle of the upper arm belongs to the upper arm alone. Bone heat left the chest (spine.3), the clavicle
# and the forearm on it (Kusznik: 59 of 65 mid-arm vertices with 2-4 bones over 0.1), so the elbow bend and the shoulder
# pulled the biceps in: mid-arm radius -23% at the aim (Mixamo's rig on the same mesh -19%). Vertices whose dominant bone
# is the limb bone, from CORE[1] to CORE[2] of its length, go fully to it, fading back to bone heat over CORE[0] at both
# ends (Kusznik: -23% -> -10%), and only within CORE_R x the bone's length of its axis: the shoulder mass 0.2 m out at
# 0.2-0.4 of a 0.28 m upper arm, moved fully with the arm, tore the shoulder (author: "the left shoulder disappeared";
# audit skin_tear 14%). Starting at 0.3 it still tore it at the hold (10%), at 0.45 8%; from 0.6 (fading in from 0.45,
# below the shoulder) 0.4%, as with no core, and the left biceps keeps -10% (no core: -37%).
# The forearm keeps its blend: the hand's weight spreads the wrist twist.
LIMB_CORE, CORE, CORE_R = ("upper_arm",), (0.15, 0.6, 0.7), 0.6


def limb_cores(arm, meshes):
    """Weights in the middle of each LIMB_CORE bone go fully to that bone; prints how many vertices changed."""
    W = arm.matrix_world; fade, lo, hi = CORE
    for o in meshes:
        gi = {g.name: i for i, g in enumerate(o.vertex_groups)}
        co = np.array([tuple(o.matrix_world @ v.co) for v in o.data.vertices])
        wts = [{g.group: g.weight for g in v.groups} for v in o.data.vertices]
        dom = np.array([max(w, key=w.get) if w else -1 for w in wts])
        for limb in LIMB_CORE:
            for s, _ in own_skeleton.SIDES:
                b = arm.data.bones.get("%s.%s" % (limb, s)); g = gi.get("%s.%s" % (limb, s))
                if b is None or g is None: continue
                a_, b_ = np.array(W @ b.head_local), np.array(W @ b.tail_local); ab = b_ - a_
                u = ((co - a_) @ ab) / max(ab @ ab, 1e-12); r = np.linalg.norm(co - a_ - u[:, None] * ab, axis=1)
                k = np.clip(np.minimum(u - (lo - fade), (hi + fade) - u) / fade, 0, 1) * (r <= CORE_R * np.linalg.norm(ab))
                n, moved = 0, 0.0
                for i in np.where((dom == g) & (k > 0))[0]:
                    w = wts[i]; other = sum(v for x, v in w.items() if x != g)
                    if other < 1e-4: continue
                    for x in list(w): w[x] = w[x] * (1 - k[i]) + (k[i] if x == g else 0.0)
                    for x, val in w.items(): o.vertex_groups[x].add([int(i)], val, "REPLACE")
                    n += 1; moved += other * k[i]
                print("auto_rig: limb core %s %s.%s - %d vertices, %.1f vertex-weights moved to it" % (o.name, limb, s, n, moved))


# throat on the head: the neck bone's weight moves to the head bone by height - none below the neck joint, all above the
# head joint. Mixamo's rig has no skin on its Neck (the head carries the throat 0.5-0.66); with bone heat's neck 0.3-0.44
# the neck lean of the aim and `head_back_deg` stretched Kusznik's throat (edge p95 1.82 vs 1.42 on Mixamo's rig, same
# motion). Bone heat also spreads neck weight down onto the shoulders: moved whole (or by position along the forward-
# leaning neck bone), the base of the neck 6-10 cm below the neck joint turned with the head into the hand at the cheek
# (hands_in_head 0 -> 1.5-1.8 cm). By height it takes only a little of the stretch (fr. 70 p95 1.82 -> 1.80, 60: 1.71 ->
# 1.67): the rest is the aim's neck lean and `head_back_deg`, i.e. the motion.
def throat_on_head(arm, meshes):
    """Moves neck-bone weight onto the head bone by height; prints how many vertices changed."""
    nb = arm.data.bones.get("neck")
    if nb is None: return
    z0, z1 = (arm.matrix_world @ nb.head_local).z, (arm.matrix_world @ nb.tail_local).z
    for o in meshes:
        n, h = o.vertex_groups.get("neck"), o.vertex_groups.get("head")
        if n is None or h is None: continue
        cnt = 0
        for v in o.data.vertices:
            w = next((g.weight for g in v.groups if g.group == n.index), 0.0)
            k = min(1.0, max(0.0, ((o.matrix_world @ v.co).z - z0) / max(z1 - z0, 1e-6)))
            if w <= 0.0 or k <= 0.0: continue
            h.add([v.index], next((g.weight for g in v.groups if g.group == h.index), 0.0) + w * k, "REPLACE")
            n.add([v.index], w * (1 - k), "REPLACE"); cnt += 1
        print("auto_rig: throat on head %s - %d vertices" % (o.name, cnt))


# head free of the arms: skin whose largest weight is the head's carries no weight of a shoulder or anything below it.
# Kusznik's head hangs forward between his shoulders: bone heat gave the face up to 0.15 of the right shoulder and the
# right cheek up to 0.10 of the right upper arm, and the aim's shoulder and arm pulled the face to one side (author).
def head_without_arms(arm, meshes):
    """Moves arm-chain weight of head-dominated vertices onto the head bone; prints how many vertices changed."""
    hb = arm.data.bones.get("head")
    if hb is None: return
    limb = {b.name for s, _ in own_skeleton.SIDES for r in ("shoulder.%s" % s,) if arm.data.bones.get(r)
            for b in [arm.data.bones[r]] + list(arm.data.bones[r].children_recursive)}
    for o in meshes:
        h = o.vertex_groups.get("head")
        if h is None: continue
        lg = {g.index for g in o.vertex_groups if g.name in limb}; cnt, moved = 0, 0.0
        for v in o.data.vertices:
            if not v.groups or max(v.groups, key=lambda g: g.weight).group != h.index: continue
            extra = [(g.group, g.weight) for g in v.groups if g.group in lg and g.weight > 0.0]
            if not extra: continue
            hw = next(g.weight for g in v.groups if g.group == h.index)
            for gi_, w in extra: o.vertex_groups[gi_].remove([v.index]); hw += w; moved += w
            h.add([v.index], hw, "REPLACE"); cnt += 1
        print("auto_rig: head without arms %s - %d vertices, %.1f vertex-weights moved to the head" % (o.name, cnt, moved))


def own_weight_rules(arm, meshes):
    limb_cores(arm, meshes); throat_on_head(arm, meshes); head_without_arms(arm, meshes)


# fist pose of the self-check: flexion about the bone's local X (own_skeleton roll rule: +X curls into the palm), every
# finger joint at once (the grip solver turns them up to 95 deg each). Kusznik (claws, 2026-11-19): 30 deg 1.2% of hand
# edges over 50% / 0.2% over 100%, 70 deg 5.5% / 1.6% (most of it the knuckle creases, the palm folds with the fingers).
FIST_DEG = {"thumb": 30.0, "other": 70.0}
TORN = (0.5, 1.0)   # edge length change (fraction of its rest length) counted as stretched / torn


def fist_check(arm, meshes):
    """Curls every finger into a fist and measures edge stretch of the hands (fingers used to tear claws when their bones
    did not follow the mesh). Prints per side the share of hand edges over each TORN level; restores the rest pose."""
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        if own_skeleton.is_finger(pb.name) and not own_skeleton.is_end(pb.name):
            deg = FIST_DEG["thumb" if pb.name.startswith("thumb") else "other"]
            pb.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), np.radians(deg))
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    for o in meshes:
        names = [g.name for g in o.vertex_groups]
        dom = []
        for v in o.data.vertices:
            best = max(v.groups, key=lambda g: g.weight, default=None)
            dom.append(names[best.group] if best is not None and best.weight > 0 else "")
        rest = np.array([v.co for v in o.data.vertices])
        ev = o.evaluated_get(dg).to_mesh()
        posed = np.array([v.co for v in ev.vertices])
        o.evaluated_get(dg).to_mesh_clear()
        e = np.array([ed.vertices[:] for ed in o.data.edges])
        l0 = np.linalg.norm(rest[e[:, 0]] - rest[e[:, 1]], axis=1)
        l1 = np.linalg.norm(posed[e[:, 0]] - posed[e[:, 1]], axis=1)
        rel = np.abs(l1 - l0) / np.maximum(l0, 1e-7)
        for s, side in (("L", "left"), ("R", "right")):
            hand = {n for n in names if n.endswith("." + s) and (n.startswith("hand.") or own_skeleton.is_finger(n))}
            m = np.array([dom[i] in hand and dom[j] in hand for i, j in e]) if len(e) else np.zeros(0, bool)
            if not m.any():
                continue
            print("auto_rig: fist %s %s - %d hand edges, changed over %s" % (o.name, side, m.sum(), ", ".join(
                "%d%%: %.2f%%" % (100 * x, 100.0 * (rel[m] > x).mean()) for x in TORN)))
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    bpy.context.view_layer.update()


if __name__ == "__main__":
    a = args()
    {"export": stage_export, "build": stage_build}[a["stage"]](a)
