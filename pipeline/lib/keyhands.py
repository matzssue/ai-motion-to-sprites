"""Hand rotation of the approved key poses put back on a clip after the model (plain numpy; key_hands.py applies it in
Blender, tests run it). Kimodo hits the key poses' joint POSITIONS but builds the clip from its rotation channel, which a
full-body key does not constrain: the knight's right hand came out 15-176 deg off the posed rotation with the hand 2-8 cm
from its target. Per key: the forearm roll that leaves the pose's own wrist twist, and the wrist that then hits the posed
hand (wrist_from_pose), within the audit's wrist limits; between keys both are spread with a smoothstep. Joint positions do
not move (a roll about the forearm's axis leaves the wrist where it is; the hand turns about the wrist). Quaternions are (w, x, y, z)."""
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


def limit_wrist(q, axis, max_twist, max_bend):
    """q (the hand under the forearm) with its twist about `axis` cut to +-max_twist deg and its swing to max_bend deg:
    the audit's wrist_twist / wrist_bend measure exactly these two."""
    q = q if q[0] >= 0 else -q
    t = twist(q, axis); sw = qmul(q, qinv(axis_angle(axis, t))); b = swing_deg(q, axis)
    t = max(-math.radians(max_twist), min(math.radians(max_twist), t))
    if b > max_bend: sw = slerp(ID, sw, max_bend / b)
    return qmul(sw, axis_angle(axis, t))


def wrist_from_pose(forearm, target, rest, pose_wrist, axis):
    """(roll rad, wrist): the forearm roll about `axis` that leaves the hand with the key pose's own wrist twist, and the
    wrist that then puts the hand exactly on `target`. hand = forearm @ R(roll) @ rest @ wrist (armature space; rest = the
    hand's rest rotation under the forearm). Kimodo's own wrist is not used: it was never constrained (round 7 raw: twist
    up to 179 deg), while the approved pose's wrist is within the audit's limits."""
    g = qmul(qinv(forearm), target)
    roll = -twist(qmul(qmul(rest, pose_wrist), qinv(g)), axis)
    return roll, qmul(qinv(rest), qmul(axis_angle(axis, -roll), g))
