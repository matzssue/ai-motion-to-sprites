"""Hand rotation of the approved key poses put back on a clip after the model (plain numpy; key_hands.py applies it in
Blender, tests run it). Kimodo hits the key poses' joint POSITIONS but builds the clip from its rotation channel, which a
full-body key does not constrain: the knight's right hand came out 15-176 deg off the posed rotation with the hand 2-8 cm
from its target. Per key: the forearm's roll about its own axis that best matches the posed hand, then the rest of the hand
rotation in the hand's own frame; between keys both deltas are spread with a smoothstep. Joint positions do not move (a
roll about the forearm's axis leaves the wrist where it is; the hand turns about the wrist). Quaternions are (w, x, y, z)."""
import math

import numpy as np

ID = np.array([1.0, 0.0, 0.0, 0.0])


def qmul(a, b):
    w1, x1, y1, z1 = a; w2, x2, y2, z2 = b
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2])


def qinv(q): return np.array([q[0], -q[1], -q[2], -q[3]]) / float(np.dot(q, q))


def axis_angle(axis, ang):
    a = np.asarray(axis, float); a = a / np.linalg.norm(a)
    return np.concatenate([[math.cos(ang / 2)], a * math.sin(ang / 2)])


def angle(a, b):
    """Rotation between two orientations, deg (0..180)."""
    return math.degrees(2 * math.acos(min(1.0, abs(float(np.dot(a, b)) / (np.linalg.norm(a) * np.linalg.norm(b))))))


def twist(q, axis):
    """Signed angle (rad, -pi..pi) of q's twist about `axis` (swing-twist decomposition)."""
    a = np.asarray(axis, float); a = a / np.linalg.norm(a)
    q = q if q[0] >= 0 else -q
    return 2 * math.atan2(float(np.dot(q[1:], a)), q[0])


def swing_deg(q, axis):
    """Angle (deg) of q without its twist about `axis`: how far it bends away from the axis."""
    q = q if q[0] >= 0 else -q
    sw = qmul(q, qinv(axis_angle(axis, twist(q, axis))))
    return math.degrees(2 * math.acos(min(1.0, abs(float(sw[0])))))


def bend_limited(base, d, axis, max_deg, step=0.05):
    """(q, kept): d with its swing scaled down until base @ q bends at most max_deg from `axis` (the twist about the axis
    kept whole); kept = the fraction of the swing left. base = the hand's own rotation under the forearm, so the bend is the
    audit's wrist_bend."""
    d = d if d[0] >= 0 else -d
    tw = axis_angle(axis, twist(d, axis)); sw = qmul(d, qinv(tw)); s = 1.0
    while s > 0 and swing_deg(qmul(base, qmul(slerp(ID, sw, s), tw)), axis) > max_deg: s = round(s - step, 6)
    s = max(s, 0.0); return qmul(slerp(ID, sw, s), tw), s


def slerp(a, b, t):
    a = np.asarray(a, float); b = np.asarray(b, float)
    d = float(np.dot(a, b))
    if d < 0: b, d = -b, -d
    if d > 0.9995: q = a + t * (b - a); return q / np.linalg.norm(q)
    th = math.acos(d); return (math.sin((1 - t) * th) * a + math.sin(t * th) * b) / math.sin(th)


def ease(t): return t * t * (3 - 2 * t)


def schedule(keys, n, loop, times=None):
    """Per time in `times` (frames, may be fractional; default 0..n-1): (i, j, eased t) — indices into the extended key list `extend(keys, n, loop)`. A loop runs
    from the last key back to the first at frame n (the clip ends where it starts); a one-shot holds the end keys."""
    ext = [f for f, _ in extend(keys, n, loop)]; out = []
    for f in (range(n) if times is None else times):
        if f <= ext[0]: out.append((0, 0, 0.0)); continue
        if f >= ext[-1]: out.append((len(ext) - 1, len(ext) - 1, 0.0)); continue
        j = next(i for i, k in enumerate(ext) if k >= f); i = j - 1
        out.append((j, j, 0.0) if abs(ext[j] - f) < 1e-6 else (i, j, ease((f - ext[i]) / (ext[j] - ext[i]))))
    return out


def extend(keys, n, loop):
    """Sorted [(frame, key)] with, for a loop, the last key copied to before frame 0 and the first to frame n."""
    ks = sorted(keys); ext = [(k, k) for k in ks]
    if loop: ext = [(ks[-1] - n, ks[-1])] + ext + [(ks[0] + n, ks[0])]
    return ext


def roll_track(rolls, n, loop, times=None):
    """{key frame: forearm roll rad} -> roll per time (`schedule`). Each key is the shortest turn from the one before (a roll of
    -166 deg after +46 deg goes on to +194, not back through 0); the copies of a loop sit a whole turn from the original
    where needed, so the seam is the shortest turn too (the same rotation)."""
    def near(v, ref):
        while v - ref > math.pi: v -= 2 * math.pi
        while v - ref < -math.pi: v += 2 * math.pi
        return v
    ks = sorted(rolls); u = [rolls[ks[0]]]
    for k in ks[1:]: u.append(near(rolls[k], u[-1]))
    if loop:   # copies: the first key after the last (shortest turn), the last before frame 0 by the same seam step
        end = near(rolls[ks[0]], u[-1]); u = [u[0] - (end - u[-1])] + u + [end]
    return [u[i] + (u[j] - u[i]) * t for i, j, t in schedule(rolls, n, loop, times)]


def quat_track(quats, n, loop, times=None):
    """{key frame: hand residual quaternion} -> one per time (`schedule`; slerp, eased)."""
    ext = extend(quats, n, loop)
    return [slerp(quats[ext[i][1]], quats[ext[j][1]], t) for i, j, t in schedule(quats, n, loop, times)]
