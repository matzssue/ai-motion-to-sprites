"""Limb weights within reach of the limb (numpy, no Blender): the auto-rig's bone heat gives a vertex the nearest bone it can
SEE in a straight line, at any distance. Cloth hanging in front of armoured legs sees none of its own bones (the plates are
in the way); the knight's tabard hem saw only the front half of the toe bone, which pokes out of the sabaton, and took
`toe.L` at 0.85-1.0 from 46 cm away: it followed the foot and stretched into a spike in front of the hips.

A limb bone's weight on a vertex farther from the bone than REACH x the bone's own skin radius (p90 distance of the
vertices whose nearest bone it is) fades out to REACH_FADE x; what is taken is given back by the vertex's neighbours along
the mesh, nearest first, so the cloth follows what the cloth around it hangs from."""
from collections import deque

import numpy as np

REACH, REACH_FADE = 3.0, 4.0
OWN_MIN = 8   # a bone with fewer own vertices has no measurable skin radius and is left alone


def seg_dist(co, a, b):
    ab = b - a
    u = np.clip(((co - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
    return np.linalg.norm(co - (a + u[:, None] * ab), axis=1)


def neighbours(n, edges):
    nb = [[] for _ in range(n)]
    for a, b in np.asarray(edges, int):
        nb[a].append(b); nb[b].append(a)
    return nb


def gate(co, edges, W, heads, tails, gated):
    """co (n,3), edges (m,2), W (n,B) weights, heads/tails (B,3) of the deforming bones, gated: bone indices held to their
    reach. Returns (new W, {bone index: (vertices touched, weight taken)})."""
    co, W = np.asarray(co, float), np.asarray(W, float).copy(); W_in = W.copy()
    D = np.stack([seg_dist(co, heads[b], tails[b]) for b in range(len(heads))], 1)
    near = D.argmin(1)
    taken, report = np.zeros(len(co)), {}
    for b in gated:
        own = near == b
        if own.sum() < OWN_MIN: continue
        r = float(np.percentile(D[own, b], 90))
        k = np.clip((REACH_FADE * r - D[:, b]) / ((REACH_FADE - REACH) * r), 0.0, 1.0)
        out = W[:, b] * (1.0 - k)
        hit = out > 1e-4
        if not hit.any(): continue
        W[hit, b] -= out[hit]; taken[hit] += out[hit]
        report[b] = (int(hit.sum()), float(out[hit].sum()))
    todo = taken > 1e-4
    if not todo.any(): return W, report
    nb = neighbours(len(co), edges)
    done = ~todo
    queued = done.copy()
    q = deque()
    for i in np.where(todo)[0]:
        if any(done[j] for j in nb[i]): q.append(i); queued[i] = True
    while q:   # breadth first from the untouched skin: each vertex takes its already settled neighbours' mean
        i = q.popleft()
        src = [j for j in nb[i] if done[j]]
        mean = W[src] / np.maximum(W[src].sum(1, keepdims=True), 1e-12)
        W[i] += taken[i] * mean.mean(0); done[i] = True
        for j in nb[i]:
            if not queued[j]: queued[j] = True; q.append(j)
    for i in np.where(~done)[0]:   # a shell with no untouched vertex keeps what is left, renormalised
        s = W[i].sum()
        W[i] = W[i] / s if s > 1e-6 else W_in[i]
    return W, report
