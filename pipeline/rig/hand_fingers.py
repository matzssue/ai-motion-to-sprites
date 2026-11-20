"""Five fingers x 3 bones per hand placed on the hand mesh (numpy/scipy, no Blender), for the own skeleton
(pipeline/lib/own_skeleton.py). Input: the mesh and the wrist, fingertip (and elbow) joints of the detector; output:
joints-file keys <Side>Hand<Finger>1..4 (knuckle .. tip). Any detector that gives these joints can feed it.

1. Hand = the mesh beyond the wrist near the hand axis, connected to the fingertip (shells closer than 0.4% of the
   character height count as connected: generated meshes are many loose shells). The axis continues the forearm
   (elbow -> wrist): towards the extreme fingertip vertex it tilted 15 deg when that vertex was a claw's corner.
2. Digits = branches of the merge tree of the geodesic distance from the wrist (along the mesh): sweeping from the far
   end back to the wrist, every part that stays separate for more than 8% of the hand length before it joins the rest
   is a digit (claw, finger, thumb). Geodesic, not along the axis: a thumb pointing sideways ends barely further along
   the axis than where it leaves the palm.
   Cloth strips hanging from a cuff (ribbons, tassels) are digits too, but thin: a digit thinner than 40% of the
   thickest is dropped, the rest are ranked by length x relative thickness^2 (Kusznik: claws 1.6-1.9 cm, ribbons
   0.6-1.0 cm mean ring radius; Wybuchacz's thinnest finger 1.3 cm).
3. Five or more digits: the 5 best ranked; the thumb is the one furthest forward (the model faces -Y; in an A or T pose
   the thumb points forward), the others index -> pinky from front to back.
   Two to four (claws): the most forward one is the thumb, four fingers are spread evenly across the rest of the hand.
   One (a mitten or fused claws): five chains spread evenly across the hand width.
4. Joints follow the mesh: every joint is the middle of a ring of the digit at one geodesic distance (below the finger
   webs: of the hand, in the digit's lane); the distances come from SOMA proportions (own_skeleton.KNUCKLE / PHALANX /
   THUMB_BASE). A station without a cross-section (a thin claw on a decimated mesh) goes between its found neighbours, so no
   two joints of a finger coincide."""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

import own_skeleton as OS

PERSIST = 0.08     # a digit stays separate over this fraction of the hand length
MIN_VERTS = 5
BRIDGE = 0.004     # shells closer than this fraction of the character height are joined
RING = 0.04        # half-width of a ring (cross-section), fraction of the hand length
THIN = 0.4         # a digit thinner than this fraction of the thickest one is cloth, not a digit
WRIST_BAND = 0.03  # vertices this close to the wrist plane (fraction of the hand length) are the geodesic source
MIN_BONE = 0.01    # shortest finger bone, fraction of the hand length


def _neighbours(n, edges):
    a = np.concatenate([edges[:, 0], edges[:, 1]]); b = np.concatenate([edges[:, 1], edges[:, 0]])
    order = np.argsort(a, kind="stable"); a, b = a[order], b[order]
    start = np.searchsorted(a, np.arange(n + 1))
    return [b[start[i]:start[i + 1]] for i in range(n)]


def hand_region(verts, tris, wrist, tip, H, elbow=None):
    """Vertex indices of the hand (step 1), its edges and the hand axis."""
    ax = tip - wrist; L = float(np.linalg.norm(ax)); ax = ax / L
    if elbow is not None and np.linalg.norm(wrist - elbow) > 1e-6:
        fa = (wrist - elbow) / np.linalg.norm(wrist - elbow)
        if fa @ ax > 0.5: ax = fa; L = float((tip - wrist) @ ax)
    rel = verts - wrist; t = rel @ ax; r = np.linalg.norm(rel - np.outer(t, ax), axis=1)
    cand = np.where((t > -0.05 * L) & (t < 1.3 * L) & (r < 0.8 * L))[0]
    loc = -np.ones(len(verts), int); loc[cand] = np.arange(len(cand))
    tt = loc[tris]; tt = tt[(tt >= 0).all(1)]
    e = np.concatenate([tt[:, [0, 1]], tt[:, [1, 2]], tt[:, [2, 0]]]) if len(tt) else np.zeros((0, 2), int)
    pairs = cKDTree(verts[cand]).query_pairs(BRIDGE * H, output_type="ndarray")
    e = np.concatenate([e, pairs.reshape(-1, 2)])
    n = len(cand)
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    seed = int(np.argmin(np.linalg.norm(verts[cand] - tip, axis=1)))
    keep = lab == lab[seed]
    idx = cand[keep]
    remap = -np.ones(n, int); remap[np.where(keep)[0]] = np.arange(len(idx))
    e2 = remap[e]; e2 = e2[(e2 >= 0).all(1)]
    return idx, e2, ax


def geodesic(P, edges, source):
    """Distance along the mesh edges from any `source` vertex (inf = not reachable)."""
    n = len(P)
    w = np.linalg.norm(P[edges[:, 0]] - P[edges[:, 1]], axis=1) + 1e-9
    g = coo_matrix((w, (edges[:, 0], edges[:, 1])), shape=(n, n)).tocsr()
    return dijkstra(g, directed=False, indices=np.where(source)[0], min_only=True)


def digits(g, edges):
    """Merge tree of `g` (step 2): [{"tip": vertex, "base": g where it joins, "verts": own vertices, "life": how long it
    stayed separate}], longest-lived first. The digit with the highest g lives forever."""
    n = len(g); nb = _neighbours(n, edges)
    L = float(g.max()) if n else 1.0
    parent = np.arange(n); done = np.zeros(n, bool)
    birth, own, junction, out = {}, {}, {}, []

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for v in np.argsort(-g, kind="stable"):
        roots = {find(u) for u in nb[v] if done[u]}
        done[v] = True
        if not roots:
            birth[v] = (g[v], v); own[v] = [v]; continue
        roots = sorted(roots, key=lambda r: -birth[r][0])
        e = roots[0]
        for o in roots[1:]:
            life = birth[o][0] - g[v]
            if life > PERSIST * L and len(own[o]) >= MIN_VERTS:
                out.append({"tip": birth[o][1], "base": float(g[v]), "verts": np.array(own[o]), "life": float(life)})
                junction[e] = max(junction.get(e, -np.inf), float(g[v]))
            else:
                own[e].extend(own[o])
            parent[o] = e; del own[o]
        parent[v] = e; own[e].append(v)
    top = find(int(np.argmax(g)))
    vs = np.array(own[top]); base = junction.get(top, -np.inf)
    out.append({"tip": birth[top][1], "base": base, "verts": vs[g[vs] > base] if np.isfinite(base) else vs, "life": np.inf})
    return sorted(out, key=lambda d: -d["life"])


class _Hand:
    """Hand vertices P with t (along the hand axis), u (towards the front = thumb side) and g (geodesic from the wrist)."""

    def __init__(self, P, edges, wrist, ax):
        self.P, self.w0, self.ax = P, wrist, ax
        u = OS.FRONT - ax * (OS.FRONT @ ax)
        if np.linalg.norm(u) < 1e-6: u = OS.UP - ax * (OS.UP @ ax)
        self.u = u / np.linalg.norm(u)
        rel = P - wrist
        self.t, self.uu = rel @ ax, rel @ self.u
        self.g = geodesic(P, edges, self.t < self.t.min() + WRIST_BAND * max(float(self.t.max()), 1e-6))
        ok = np.isfinite(self.g)
        self.g[~ok] = -1.0
        self.ok = np.where(ok)[0]
        self.L = float(self.g.max())
        self.filled = []   # fingers with a station placed between its neighbours (no ring there)

    def thickness(self, d):
        """Mean distance of the digit's middle ring from the ring's centre."""
        vs = d["verts"]; g_tip = float(self.g[d["tip"]])
        base = d["base"] if np.isfinite(d["base"]) else float(self.g[vs].min())
        m = vs[np.abs(self.g[vs] - 0.5 * (base + g_tip)) < 0.75 * RING * self.L]
        if len(m) < 3: return 0.0
        q = self.P[m]
        return float(np.linalg.norm(q - q.mean(0), axis=1).mean())

    def ring(self, pool, s, u=None, band=None):
        """Middle (bounding-box centre) of the vertices of `pool` at geodesic distance s (within `band` of lane u), or None."""
        m = np.abs(self.g[pool] - s) < RING * self.L
        if u is not None: m &= np.abs(self.uu[pool] - u) < band
        if m.sum() < 2: return None
        q = self.P[pool[m]]
        return 0.5 * (q.min(0) + q.max(0))

    def tip(self, pool, a, b):
        """Fingertip of a digit whose last joints are a -> b: the middle of its end cap along a -> b, pushed out to the cap's
        furthest vertex (the farthest vertex alone sat on a claw's corner; a geodesic cap is lopsided)."""
        d = b - a
        if np.linalg.norm(d) < 1e-9: d = self.ax
        d = d / np.linalg.norm(d)
        q = self.P[pool]; x = (q - b) @ d
        cap = q[x >= x.max() - RING * self.L]
        c = 0.5 * (cap.min(0) + cap.max(0))
        return c + d * max(0.0, float(((cap - c) @ d).max()))


def _between(h, S, pts, far):
    """Stations without a ring (None in `pts`, at geodesic distances S): on the line between the nearest found neighbours,
    by geodesic distance; below the first found one the wrist, above the last the digit's far vertex `far`. A long thin claw
    on a decimated mesh has rings of fewer than 2 vertices: copying the previous joint gave a zero-length bone (Padlinozerca)."""
    anchors = [(0.0, h.w0)] + [(s, p) for s, p in zip(S, pts) if p is not None] + [(float(h.g[far]), h.P[far])]
    out = []
    for s, p in zip(S, pts):
        if p is None:
            lo, hi = [x for x in anchors if x[0] <= s], [x for x in anchors if x[0] > s]
            (s0, a), (s1, b) = max(lo, key=lambda x: x[0]) if lo else anchors[0], min(hi, key=lambda x: x[0]) if hi else anchors[-1]
            p = a + (b - a) * (s - s0) / (s1 - s0) if s1 > s0 else a
        out.append(p)
    return out


def _apart(h, pts):
    """Every joint at least MIN_BONE x the hand length from the previous one, pushed along the chain (the last guard against a
    zero-length bone, which Blender cannot build)."""
    out, m = [pts[0]], MIN_BONE * h.L
    for i, p in enumerate(pts[1:], 1):
        d = p - out[-1]
        if np.linalg.norm(d) < m:
            later = [q - out[-1] for q in pts[i + 1:] if np.linalg.norm(q - out[-1]) >= m]
            d = later[0] if later else (out[-1] - out[-2] if len(out) > 1 else h.ax)
            p = out[-1] + d / np.linalg.norm(d) * m
        out.append(p)
    return out


def _chain(h, finger, own, g_tip, base, lane, u0, band):
    """Knuckle .. tip of one finger: geodesic stations from SOMA proportions; on the digit's `own` vertices above its
    `base`, on the hand vertices of its lane (`lane`, within `band` of u0) below."""
    gk = OS.KNUCKLE.get(finger, OS.KNUCKLE["middle"]) * g_tip
    if base is not None: gk = min(gk, base)
    f = OS.PHALANX[finger]
    S = (gk, gk + f[0] * (g_tip - gk), gk + (f[0] + f[1]) * (g_tip - gk))
    pts = []
    for s in S:
        p = h.ring(own, s) if base is not None and s > base else None
        if p is None: p = h.ring(lane, s, u0, band)
        pts.append(p)
    if any(p is None for p in pts): h.filled.append(finger)
    out = _between(h, S, pts, own[np.argmax(h.g[own])])
    out.append(h.tip(own, out[-2], out[-1]))
    return _apart(h, out)


def _thumb(h, own, g_tip, base, Lm):
    """Thumb: base (CMC) inside the palm near the wrist on the thumb side, MCP where the thumb leaves the hand, IP between
    it and the tip (SOMA proportions)."""
    every = h.ok
    tb = OS.THUMB_BASE[0] * Lm
    m = every[np.abs(h.t[every] - tb) < RING * h.L]
    if len(m):
        q = h.P[m]; c = 0.5 * (q.min(0) + q.max(0)); lo, hi = float(h.uu[m].min()), float(h.uu[m].max())
        uc = float((c - h.w0) @ h.u)
        j0 = c + h.u * (min(uc + OS.THUMB_BASE[1] * Lm, hi - 0.25 * (hi - lo)) - uc)
    else:
        j0 = h.w0 + tb * h.ax
    gm = (base if base is not None and np.isfinite(base) else float(h.g[own].min())) + RING * h.L
    j1 = h.ring(own, gm)
    if j1 is None: j1 = h.P[own].mean(0)
    f = OS.PHALANX["thumb"]
    s2 = gm + f[1] / (f[1] + f[2]) * (g_tip - gm)
    j2 = h.ring(own, s2)
    if j2 is None:
        h.filled.append("thumb"); j2 = _between(h, (gm, s2), [j1, None], own[np.argmax(h.g[own])])[1]
    return _apart(h, [j0, j1, j2, h.tip(own, j1, j2)])


def place(verts, tris, wrist, tip, H, elbow=None):
    """{finger: [knuckle, joint 2, joint 3, tip]} for one hand, and a one-line report."""
    wrist, tip = np.asarray(wrist, float), np.asarray(tip, float)
    idx, edges, ax = hand_region(verts, tris, wrist, tip, H, None if elbow is None else np.asarray(elbow, float))
    h = _Hand(verts[idx], edges, wrist, ax)
    ok = np.zeros(len(idx), bool); ok[h.ok] = True
    D = [d for d in digits(np.where(ok, h.g, -1.0), edges) if ok[d["tip"]]]
    found = len(D)
    if D:
        th = [h.thickness(d) for d in D]; top = max(th) or 1.0
        for d, x in zip(D, th):
            length = float(h.g[d["tip"]]) - (d["base"] if np.isfinite(d["base"]) else float(h.g[d["verts"]].min()))
            d["score"] = length * (x / top) ** 2 if x >= THIN * top else -1.0
        D = sorted((d for d in D if d["score"] >= 0), key=lambda d: -d["score"])
    cloth = "" if len(D) == found else ", %d thin (cloth) dropped" % (found - len(D))
    out = {}
    if len(D) >= 5:
        D = D[:5]
        fwd = [h.uu[d["verts"]].mean() for d in D]
        th = int(np.argmax(fwd)); rest = sorted((i for i in range(5) if i != th), key=lambda i: -fwd[i])
        Lm = max(float(h.t[d["tip"]]) for d in D)
        d = D[th]; out["thumb"] = _thumb(h, d["verts"], float(h.g[d["tip"]]), d["base"], Lm)
        us = sorted(float(h.uu[D[i]["verts"]].mean()) for i in rest)
        band = 0.5 * min(b - a for a, b in zip(us, us[1:])) if len(us) > 1 else 0.06 * h.L
        for f, i in zip(OS.FINGERS[1:], rest):
            d = D[i]; low = d["verts"][h.g[d["verts"]] < d["base"] + RING * h.L]
            u0 = float(h.uu[low if len(low) else d["verts"]].mean())
            out[f] = _chain(h, f, d["verts"], float(h.g[d["tip"]]), d["base"], h.ok, u0, band)
        return out, "%d digits found%s, 5 used%s" % (found, cloth, _filled(h))
    pool = h.ok
    if len(D) >= 2:
        fwd = [h.uu[d["verts"]].mean() for d in D]
        d = D[int(np.argmax(fwd))]
        out["thumb"] = _thumb(h, d["verts"], float(h.g[d["tip"]]), d["base"], float(h.t.max()))
        pool = np.setdiff1d(pool, d["verts"])
        names, report = OS.FINGERS[1:], "%d digits found%s: thumb + 4 fingers spread across the rest of the hand" % (found, cloth)
    else:
        names, report = OS.FINGERS, "%d digit found%s: 5 fingers spread across the hand" % (found, cloth)
    gw = 0.5 * float(h.g[pool].max())
    m = pool[np.abs(h.g[pool] - gw) < 2 * RING * h.L]
    if not len(m): m = pool   # nothing at half the length (the rest of a hand without the thumb has a gap there): its whole width
    lo, hi = float(h.uu[m].min()), float(h.uu[m].max())
    k = len(names); band = 0.5 * (hi - lo) / k
    for i, f in enumerate(names):
        u0 = hi - (i + 0.5) * (hi - lo) / k
        lane = pool[np.abs(h.uu[pool] - u0) < band]
        if not len(lane): lane = pool
        g_tip = float(h.g[lane].max())
        out[f] = _chain(h, "middle" if f == "thumb" else f, lane, g_tip, None, lane, u0, band)
    return out, report + _filled(h)


def _filled(h):
    return "; no cross-section at a joint of %s: placed between its neighbours" % ", ".join(sorted(set(h.filled))) if h.filled else ""


def finger_joints(verts, tris, joints, H):
    """Joints-file keys of both hands from `joints` (needs <Side>Hand and <Side>Tip, uses <Side>ForeArm)
    -> ({key: point}, {side: report})."""
    out, rep = {}, {}
    for _, S in OS.SIDES:
        chains, rep[S] = place(verts, tris, joints[S + "Hand"], joints[S + "Tip"], H, joints.get(S + "ForeArm"))
        for f, pts in chains.items():
            for i, p in enumerate(pts):
                out[OS.finger_key(S, f, i + 1)] = np.asarray(p, float)
    return out, rep
