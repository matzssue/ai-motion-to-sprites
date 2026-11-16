"""Shared Blender helpers: body regions from skin weights, a region BVH at a given frame,
penetration depth of points into a region, wrist bend/twist angles."""
import math
import numpy as np
from mathutils import Quaternion, Vector
from mathutils.bvhtree import BVHTree

# bone names without the `mixamorig:` prefix; fingers = `finger_*` bones from prop_in_hands plus Mixamo fingers
REGIONS = {
    "head": ("Head", "Neck", "HeadTop_End"),
    "torso": ("Spine", "Spine1", "Spine2", "Hips"),
    "clavicles": ("LeftShoulder", "RightShoulder"),
    "legs": ("LeftUpLeg", "RightUpLeg", "LeftLeg", "RightLeg"),
    "forearms": ("LeftForeArm", "RightForeArm"),
    "hands": ("LeftHand", "RightHand"),
}
FINGER_PREFIX = "finger_"


def is_finger(name):
    return name.startswith(FINGER_PREFIX) or ("Hand" in name and name not in ("LeftHand", "RightHand"))


def dominant(mesh):
    names = [g.name.split(":")[-1] for g in mesh.vertex_groups]
    dom = np.full(len(mesh.data.vertices), "", dtype=object)
    for v in mesh.data.vertices:
        best, w = "", 0.0
        for g in v.groups:
            if g.weight > w:
                best, w = names[g.group], g.weight
        dom[v.index] = best
    return dom


def masks(dom):
    out = {r: np.isin(dom, b) for r, b in REGIONS.items()}
    out["fingers"] = np.array([is_finger(d) for d in dom])
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


ARMS = ("LeftArm", "RightArm", "LeftForeArm", "RightForeArm", "LeftHand", "RightHand")


def labels(dom):
    """Region of every vertex; arms (from the upper arm down) and fingers = '' (those are what gets tested)."""
    lab = np.full(len(dom), "", dtype=object)
    for r in ("head", "torso", "clavicles", "legs"):
        lab[np.isin(dom, REGIONS[r])] = r
    lab[np.array([d in ARMS or is_finger(d) for d in dom])] = ""
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


def bone_side(name):
    """'L' / 'R' / '' for arm, hand and finger bones (`finger_R0_1`, `LeftHandIndex1`)."""
    if name.startswith(FINGER_PREFIX): return name[len(FINGER_PREFIX)]
    return "L" if name.startswith("Left") else "R" if name.startswith("Right") else ""


def joint_angles(parent_rest, child_rest, parent, child):
    """Bend and twist of the child relative to the parent since rest (deg); twist around the child's Y axis."""
    q = ((parent_rest.inverted() @ child_rest).inverted() @ (parent.inverted() @ child)).to_quaternion()
    tw = Quaternion((q.w, 0, q.y, 0)).normalized()
    return math.degrees((q @ tw.inverted()).angle), (math.degrees(2 * math.atan2(q.y, q.w)) + 180) % 360 - 180
