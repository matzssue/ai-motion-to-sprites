"""Arm skin twist (no Blender needed): the angle of every vertex around the segment axis (upper arm with shoulder, forearm)
relative to the torso, carried onto the posed axis by the shortest rotation. Healthy skin rotates in rings together
(coherence ~1, small twist along the segment); a "candy wrapper" scatters the angles (coherence drops) or winds them
into a spiral (large twist). Thresholds and measurements: README, "Skin twist"."""
import numpy as np

TWIST_MAX = 120.0      # deg per segment length. Approved clips: up to 60; broken overhead swing: 210-260
SPREAD_MAX = 0.5       # 1 - coherence. Approved: 0.41 and below; broken swing: 0.45-0.80
SEGMENTS = (("upper_arm", "forearm", ("upper_arm", "shoulder")), ("forearm", "hand", ("forearm",)))   # segment, end, vertex roles
_GRID = np.radians(np.arange(-600, 601, 10))
_rng = np.random.default_rng(0)


def _minrot(a, b):
    v = np.cross(a, b); c = float(a @ b); s = float(np.linalg.norm(v))
    if s < 1e-9:
        if c > 0: return np.eye(3)
        p = np.cross(a, [1.0, 0, 0]); p = p if np.linalg.norm(p) > 1e-6 else np.cross(a, [0, 1.0, 0]); v, s, c = p / np.linalg.norm(p), 1.0, -1.0
    k = v / s; K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]]); th = np.arctan2(s, c)
    return np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * K @ K


def segments(prof, side):
    """[(segment bone, end bone, vertex bones)] of one arm from the skeleton profile; a missing role drops the segment
    (shoulder: only from the vertex bones)."""
    return [(prof.bone(a, side), prof.bone(b, side), [prof.bone(x, side) for x in xs if prof.has(x, side)])
            for a, b, xs in SEGMENTS if prof.has(a, side) and prof.has(b, side)]


def select(dom, rest, heads0, segs, samples=600):
    """vertex indices of each arm segment {segment bone: indices}; dom = dominant bone per vertex, heads0 = {bone: rest head},
    segs = segments(prof, side)"""
    out = {}
    for a, b, bones in segs:
        if a not in heads0 or b not in heads0: continue
        a0, b0 = heads0[a], heads0[b]; L = np.linalg.norm(b0 - a0); d0 = (b0 - a0) / L
        ii = np.where(np.isin(dom, bones))[0]
        p = rest[ii] - a0; t = p @ d0 / L; R = np.linalg.norm(p - np.outer(p @ d0, d0), axis=1)
        ii = ii[(t > -0.35) & (t < 1.05) & (R > 0.02 * L)]
        if len(ii) > samples: ii = np.sort(_rng.choice(ii, samples, replace=False))
        if len(ii) >= 20: out[a] = ii
    return out


def twist(rest, co, ii, a0, b0, a1, b1, R_torso):
    """(twist deg per segment length, spread 0..1) for vertices ii; a/b = segment end heads at rest (0) and posed (1)"""
    L = np.linalg.norm(b0 - a0); d0 = (b0 - a0) / L; d1 = (b1 - a1) / np.linalg.norm(b1 - a1)
    T = _minrot(R_torso @ d0, d1) @ R_torso
    p0 = rest[ii] - a0; t = p0 @ d0 / L; r0 = (p0 - np.outer(p0 @ d0, d0)) @ T.T
    p1 = co[ii] - a1; r1 = p1 - np.outer(p1 @ d1, d1)
    th = np.arctan2(np.cross(r0, r1) @ d1, (r0 * r1).sum(1))
    E = np.abs(np.exp(1j * (th[None, :] - _GRID[:, None] * t[None, :])).mean(1)); k = int(E.argmax())
    return float(np.degrees(_GRID[k])), float(1.0 - E[k])
