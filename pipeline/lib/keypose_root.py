"""Hip position of a hand-set key pose carried back to Kimodo (plain numpy; keyposes_to_kimodo.py and kimodo_keyposes.py use
it, tests run it). The retarget (soma_to_mixamo.py) moves the rig's hips by the source's hip travel turned by C and scaled
by k = rig hip height / source hip height (above the lowest foot, rest pose). Key poses passed rotations only, so a crouch
posed by hand reached Kimodo at the base sample's standing hip height and floated (Padlinozerca: lowest joint 34 cm up)."""
import math

import numpy as np

KIMODO_TO_BLENDER = np.array([[1.0, 0, 0], [0, 0, -1], [0, 1, 0]])   # Kimodo (Y up) -> Blender (Z up)
BVH_UNITS = 100.0   # Kimodo writes its BVH in cm (kimodo/exports/bvh.py); Blender imports 1 BVH unit = 1 unit


def retarget(src, src_rest, tgt_rest, C, k):
    """soma_to_mixamo.py: rig hips for source hips `src` (both Blender world)."""
    return np.asarray(tgt_rest) + np.asarray(C) @ (np.asarray(src) - src_rest) * k


def source(tgt, src_rest, tgt_rest, C, k):
    """The inverse: source hips (Blender world of the imported BVH) that the retarget turns into rig hips `tgt`."""
    return np.asarray(src_rest) + np.asarray(C).T @ (np.asarray(tgt) - tgt_rest) / k


def to_kimodo(v, src_scale=1.0):
    """Blender world point of the imported BVH -> Kimodo metres (Y up)."""
    return KIMODO_TO_BLENDER.T @ np.asarray(v, float) / (BVH_UNITS * src_scale)


# Between keys: the root's heading and (x, z). Kimodo takes both per frame (Root2DConstraintSet) and a full-body key carries
# its own (hip line, pelvis). Non-key frames used to get heading forward and the track, so a key with the pelvis turned or
# shifted snapped there and back (knight round 7: yaw -10/-17/-19/+29 deg only on key frames, steps up to 16.5 deg/frame,
# shins shaking 2.6-3.1 cm; round 5 with unturned poses 0..3 deg, 0.9 cm). Now the path runs through the keys.
MAX_TURN = 10.0   # deg per Kimodo frame (300 deg/s at 30 fps): a faster pelvis turn between keys is warned about


def heading(right_hip, left_hip):
    """Kimodo's root heading angle (rad) from the hip joints (Y up): atan2(dz, -dx) of right - left
    (kimodo/motion_rep/feature_utils.py compute_heading_angle); 0 = facing +Z, the track's direction."""
    d = np.asarray(right_hip, float) - np.asarray(left_hip, float)
    return math.atan2(d[2], -d[0])


def unwrap(angles):
    """Each angle the shortest turn from the one before (+170 then -170 deg is 20 deg on, not 340 back)."""
    out = [float(angles[0])]
    for a in angles[1:]:
        out.append(out[-1] + (float(a) - out[-1] + math.pi) % (2 * math.pi) - math.pi)
    return out


def pchip(xs, ys, x):
    """Monotone cubic through (xs, ys) (Fritsch-Carlson), held flat outside, slope 0 at the end keys: the curve does not stop
    on a key in the middle of a turn (a smoothstep per gap would) and does not overshoot a key that reverses the turn."""
    xs = np.asarray(xs, float); ys = np.asarray(ys, float); x = np.asarray(x, float)
    n = len(xs)
    if n == 1: return np.full(x.shape, ys[0])
    h = np.diff(xs); dl = np.diff(ys) / h; m = np.zeros(n)
    for k in range(1, n - 1):
        if dl[k - 1] * dl[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / dl[k - 1] + w2 / dl[k])
    i = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, n - 2)
    t = np.clip((x - xs[i]) / h[i], 0.0, 1.0); t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * h[i] * m[i] + (-2 * t3 + 3 * t2) * ys[i + 1]
            + (t3 - t2) * h[i] * m[i + 1])


def root_between(key_frames, key_yaw, key_xz, n_frames):
    """Per Kimodo frame 0..n-1: (yaw rad, (x, z) offset from the track) through the keys' own values; before the first key
    and after the last one held. All keys facing forward on the track give exactly 0 everywhere (the old payload)."""
    order = np.argsort(key_frames); f = np.asarray(key_frames, float)[order]
    yaw = unwrap(np.asarray(key_yaw, float)[order]); xz = np.asarray(key_xz, float)[order]
    t = np.arange(n_frames)
    return pchip(f, yaw, t), np.stack([pchip(f, xz[:, 0], t), pchip(f, xz[:, 1], t)], axis=1)
