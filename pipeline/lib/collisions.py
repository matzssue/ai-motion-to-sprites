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


ARM_REGIONS = (("upper_arms", "upper_arm"), ("forearms", "forearm"), ("hands", "hand"))
GRIP_ZONE = 0.25   # share of a holding arm's forearm next to its wrist that may touch the prop (the prop lies in that palm)


def labels_all(dom, rig):
    """Region of every vertex over the WHOLE skin: the body regions plus upper arms, forearms, hands and fingers by role."""
    lab = labels(dom, rig)
    for r, role in ARM_REGIONS:
        lab[np.isin(dom, rig.prof.bones(role))] = r
    lab[np.isin(dom, sorted(rig.fingers))] = "fingers"
    return lab


def skin_tree(co, tris, lab, side):
    """BVH of the whole labelled skin + region and side of every face (for prop_in_body)."""
    t = tris[(lab[tris] != "").all(1)]
    return BVHTree.FromPolygons([Vector(c) for c in co], t.tolist(), all_triangles=True), lab[t[:, 0]], side[t[:, 0]]


def prop_in_body(tree, reg, side, pts, holders, reach=0.12, rest=None):
    """Deepest penetration of prop points into the whole skin, per region and side: {"forearms.R": (m, point)}.
    Only the grip zone of every holding side in `holders` ({side: (wrist, forearm length)}) is left out: its hand, fingers
    and the forearm within GRIP_ZONE x its length of the wrist. A rest contact (a butt on the shoulder) is not left out:
    the approved Mixamo shot's butt sat 7.4 cm inside the right shoulder and no audit saw it. Only an armpit rest
    `rest` = (rear end, front end, side, shoulder joint, elbow) on an aim frame: the stock's rear POCKET_SPAN in the torso
    or in that side's upper arm within POCKET_ARM of its length from the shoulder joint goes under "pocket" (scored
    against POCKET_REST). Further down the arm it is the elbow, not the armpit."""
    out = {}
    if rest is not None:
        rb = np.asarray(rest[0], float); ln = float(np.linalg.norm(np.asarray(rest[1]) - rb)); rst = (np.asarray(rest[1]) - rb) / ln
        aS = np.asarray(rest[3], float); aE = np.asarray(rest[4], float) - aS; aL = float(aE @ aE)
    for p in pts:
        v = Vector(p); loc, nor, fi, d = tree.find_nearest(v, reach)
        if loc is None or (v - loc).dot(nor) >= 0: continue
        r, s = reg[fi], side[fi]
        if s in holders and (r in ("hands", "fingers") or (r == "forearms" and (v - holders[s][0]).length < GRIP_ZONE * holders[s][1])):
            continue
        k = r + ("." + s if s else "")
        if rest is not None and (r == "torso" or (r == "upper_arms" and s == rest[2]
                                                  and float((np.asarray(loc) - aS) @ aE) <= POCKET_ARM * aL)) and (
                -0.03 <= float((np.asarray(p) - rb) @ rst) <= POCKET_SPAN * ln):
            k = "pocket"
        if d > out.get(k, (0.0,))[0] and inside(tree, v): out[k] = (d, p)
    return out


# armpit pocket: a prop's rear end resting under an arm lies between the inner upper arm and the ribs - from POCKET_U[0] to
# POCKET_U[1] of the upper arm below the shoulder joint, not outside the arm's axis, not in front of or behind the arm by
# more than its radius + the stock's, and within POCKET_TOUCH of the torso and of the upper arm's skin. Kusznik round 6:
# butt on the forearm in front of the elbow (author: "it does not go under the armpit")
# The author's accepted pose on Kusznik (round 8) has the stock 0.67-0.72 of the upper arm below the shoulder joint
POCKET_U, POCKET_TOUCH = (0.1, 0.75), 0.06
# the stock may also run through the pocket with its rear end out behind the back (author's own aim pose, round 8: the end
# 7.4 cm off the pocket while the stock lay in it): any section of the rear POCKET_SPAN of the prop's length counts
POCKET_SPAN = 0.35
# ... and rests there in the skin: the author's accepted aim pose on Kusznik (round 8) has the stock 3.9 cm in the torso
# side of the pocket, which the general prop_in_body limit (1.5 cm) failed. Scored as prop_in_pocket, aim frames only
POCKET_REST = 0.045
# ... but only in the armpit: the torso side and the upper arm's top POCKET_ARM (its fold at the shoulder joint). Kusznik
# round 8, the solver's own aim: the stock 3.3 cm in the upper arm's middle and against the forearm, the elbow pressed to
# the body (author: "the crossbow goes into the elbow instead of the armpit"); the whole upper arm was exempt and it
# passed. The author's accepted aim rests on the ribs (3.9-4.2 cm) and touches the upper arm 0.1 cm
POCKET_ARM = 0.3


def stock_end(pc):
    """(end of the prop's long axis nearest-first pair, its radius): both ends (mean of the last 3 cm) and the median
    distance of the points from the axis."""
    c0 = pc.mean(0); ax = np.linalg.svd(pc - c0, full_matrices=False)[2][0]; pr = (pc - c0) @ ax
    ends = [pc[pr < pr.min() + 0.03].mean(0), pc[pr > pr.max() - 0.03].mean(0)]
    return ends, float(np.median(np.linalg.norm((pc - c0) - np.outer(pr, ax), axis=1)))


def pocket_gap(b, S, E, up, out, r_stock, ua_r, tree, ua_pts, front=None):
    """How far a rear end `b` is from the armpit pocket of the arm with shoulder joint S and elbow E (m, 0 = in it).
    up = the spine's direction, out = away from the body on that side, tree = the body without arms. With the prop's
    other end `front`, the nearest section of the stock's rear POCKET_SPAN (1 cm steps) counts instead of the end.
    A section's gap is the largest of six distances and the answer is the smallest gap: a section whose first distances
    already reach the smallest gap so far skips the two surface queries (the dear ones), and 0 ends the walk."""
    fw = np.cross(up, out); la = np.linalg.norm(E - S); sections = [b]; best = None
    if front is not None:
        ln = float(np.linalg.norm(front - b)); st = (front - b) / ln
        sections = [b + st * t for t in np.arange(0.0, POCKET_SPAN * ln + 1e-9, 0.01)]
    for p in sections:
        h = (S - p) @ up; u = np.clip((p - S) @ (E - S) / la ** 2, 0, 1); a = S + u * (E - S)
        gap = max(POCKET_U[0] * la - h, h - POCKET_U[1] * la, (p - a) @ out, abs((p - a) @ fw) - ua_r - r_stock)
        if best is not None and max(0.0, float(gap)) >= best: continue
        loc, _, _, dt = tree.find_nearest(Vector(p), 1.0)
        gap = max(gap, (dt if loc is not None else 1.0) - POCKET_TOUCH)
        if best is not None and max(0.0, float(gap)) >= best: continue
        da = float(np.linalg.norm(ua_pts - p, axis=1).min()) if len(ua_pts) else 1.0
        g = max(0.0, float(max(gap, da - POCKET_TOUCH)))
        if best is None or g < best: best = g
        if best == 0.0: break
    return best


def limb_radius(co, sel, a, b):
    """Median distance of the vertices `sel` from the segment a-b (an upper arm's skin radius at rest)."""
    u = np.clip((co[sel] - a) @ (b - a) / ((b - a) @ (b - a)), 0, 1)
    return float(np.median(np.linalg.norm(co[sel] - (a + u[:, None] * (b - a)), axis=1)))


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
