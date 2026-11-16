"""Blender half of the auto-rig (`auto_rig.py`): mesh export and rig build.
blender -b --python pipeline/rig/auto_rig_blender.py -- export --src=<x>_for_rig.fbx --out=<x>.npz
blender -b --python pipeline/rig/auto_rig_blender.py -- build --src=... --joints=<x>.json --template=<mixamo skeleton>.fbx --out=rig_base.fbx"""
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector


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
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    arm.select_set(True)
    bpy.ops.export_scene.fbx(filepath=os.path.abspath(a["out"]), use_selection=True, add_leaf_bones=False, bake_anim=False,
                             path_mode="COPY", embed_textures=True, object_types={"ARMATURE", "MESH"})
    print("auto_rig: saved %s" % a["out"])


if __name__ == "__main__":
    a = args()
    {"export": stage_export, "build": stage_build}[a["stage"]](a)
