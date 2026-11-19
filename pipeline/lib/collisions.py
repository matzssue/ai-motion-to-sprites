"""Shared Blender helpers: body regions from skin weights, a region BVH at a given frame,
penetration depth of points into a region, wrist bend/twist angles."""
import math
import numpy as np
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree
import skeleton

FINGER_PREFIX = "finger_"   # bones prepare_rig grows out of claws (the tool's own names, any skeleton)
REGIONS = skeleton.REGIONS


def rig_of(arm, spec=None, exclude=()):
    """Skeleton profile (name/path, None = default) bound to a Blender armature (skeleton.Rig, profile in `.prof`)."""
    return skeleton.for_rig(spec, {b.name: b.parent.name if b.parent else None for b in arm.data.bones}, exclude)


def dominant(mesh):
    """Bone (full vertex group name) with the largest weight of every vertex."""
    names = [g.name for g in mesh.vertex_groups]
    dom = np.full(len(mesh.data.vertices), "", dtype=object)
    for v in mesh.data.vertices:
        best, w = "", 0.0
        for g in v.groups:
            if g.weight > w:
                best, w = names[g.group], g.weight
        dom[v.index] = best
    return dom


def masks(dom, rig):
    out = {r: np.isin(dom, rig.prof.region_bones(r)) for r in REGIONS}
    out["forearms"] = np.isin(dom, rig.prof.bones("forearm")); out["hands"] = np.isin(dom, rig.prof.bones("hand"))
    out["fingers"] = np.isin(dom, sorted(rig.fingers))
    return out


def vertices(obj, depsgraph):
    """World positions of the deformed mesh. Multiplication in float32 in mathutils order: bit-identical to
    `matrix_world @ v.co` (a per-vertex loop took 42 ms per frame on a 25k-triangle character, this 1.7 ms)."""
    e = obj.evaluated_get(depsgraph); m = e.to_mesh(); n = len(m.vertices)
    c = np.empty(n * 3, np.float32); m.vertices.foreach_get("co", c); e.to_mesh_clear()
    c = c.reshape(n, 3); M = np.array(obj.matrix_world, np.float32); x, y, z = c[:, 0], c[:, 1], c[:, 2]
    return np.stack([x * M[i, 0] + y * M[i, 1] + z * M[i, 2] + M[i, 3] for i in range(3)], 1).astype(np.float64)


def bvh(co, tris, vmask=None):
    t = tris if vmask is None else tris[vmask[tris].all(1)]
    return BVHTree.FromPolygons([Vector(c) for c in co], t.tolist(), all_triangles=True) if len(t) else None


_DIRS = [Vector(v).normalized() for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
                                           (1, 1, 1), (-1, -1, 1), (1, -1, -1), (-1, 1, -1))]


def inside(tree, p, share=0.8):
    """Ray vote: inside when >= `share` of rays first hit the BACK of a face.
    The sign of the nearest face alone is wrong next to open sheets (rags, belts, cloaks): a point
    behind a sheet looks 10 cm "inside" (measured on a character at rest)."""
    back = 0
    for d in _DIRS:
        loc, nor, _, _ = tree.ray_cast(p + d * 1e-4, d, 1.0)
        if loc is not None and nor.dot(d) > 0: back += 1
    return back >= share * len(_DIRS)


def depth(tree, pts, reach=0.15):
    """Deepest penetration of the points into the mesh (m) and that point's index. Mesh normals point outward;
    a point farther than `reach` from the surface counts as outside (regions are open where they meet)."""
    if tree is None or len(pts) == 0:
        return 0.0, -1
    best, bi = 0.0, -1
    for i, p in enumerate(pts):
        p = Vector(p)
        loc, nor, _, d = tree.find_nearest(p, reach)
        if loc is not None and (p - loc).dot(nor) < 0 and d > best and inside(tree, p):
            best, bi = d, i
    return best, bi


def labels(dom, rig):
    """Region of every vertex; arms (from the upper arm down) and fingers = '' (those are what gets tested)."""
    lab = np.full(len(dom), "", dtype=object)
    for r in REGIONS:
        lab[np.isin(dom, rig.prof.region_bones(r))] = r
    lab[np.isin(dom, sorted(rig.arms | rig.fingers))] = ""
    return lab


def body_tree(co, tris, lab):
    """BVH of the body without arms (almost closed: holes only at the shoulders) + the region of every face."""
    keep = (lab[tris] != "").all(1)
    t = tris[keep]
    reg = lab[t[:, 0]]
    return BVHTree.FromPolygons([Vector(c) for c in co], t.tolist(), all_triangles=True), reg


def depths(tree, reg, pts, reach=0.12):
    """Deepest penetration of the points into the body, per region of the nearest face: {region: (m, point, index)}."""
    out = {}
    for i, p in enumerate(pts):
        v = Vector(p)
        loc, nor, fi, d = tree.find_nearest(v, reach)
        if loc is None or (v - loc).dot(nor) >= 0: continue
        r = reg[fi]
        if d > out.get(r, (0.0,))[0] and inside(tree, v): out[r] = (d, p, i)
    return out


def joint_angles(parent_rest, child_rest, parent, child):
    """Bend and twist of the child relative to the parent since rest (deg); twist around the child's Y axis."""
    q = ((parent_rest.inverted() @ child_rest).inverted() @ (parent.inverted() @ child)).to_quaternion()
    tw = Quaternion((q.w, 0, q.y, 0)).normalized()
    return math.degrees((q @ tw.inverted()).angle), (math.degrees(2 * math.atan2(q.y, q.w)) + 180) % 360 - 180
