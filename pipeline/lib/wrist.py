"""The wrist of a hand that holds a weapon, split the way a wrist moves: flexion / extension and radial / ulnar deviation
(plain numpy; motion_audit.py gates with it, recipes/swing_arm.py costs with it, tests run it).
One cone for "the wrist's bend" hides a hand hanging sideways under the forearm: 73 deg toward the little finger passed an
85 deg cone. Split, the same frame reads flexion and deviation each against its own, much smaller, limit."""
import numpy as np

Y = np.array([0.0, 1.0, 0.0])   # a bone's own long axis


def unit(v):
    v = np.asarray(v, float); return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def hand_axes(y, thumb, others, side):
    """The hand's frame at rest: (radial, palm) unit vectors across the hand bone's direction `y`. `radial` runs along the
    knuckles toward the thumb's side, `palm` points out of the palm. `thumb`: where the thumb's first bone starts,
    `others` [n, 3]: where the other fingers' first bones start, `side` "L" / "R"; all in one space. None when no other
    finger tells the sides apart."""
    y = unit(y); o = np.atleast_2d(np.asarray(others, float))
    if o.size == 0: return None
    flat = lambda p: p - np.outer(p @ y, y)   # noqa: E731  across the hand's direction
    c = o.mean(0); r = flat((np.asarray(thumb, float) - c)[None])[0]
    if len(o) >= 2:   # the knuckle line itself: a thumb starts nearer the palm than the knuckles
        s, vt = np.linalg.svd(flat(o - c))[1:]
        if s[0] > 1e-6: k = flat(vt[:1])[0]; r = k if k @ r >= 0 else -k
    if np.linalg.norm(r) < 1e-9: return None
    r = unit(r); return r, unit(np.cross(r, y) if side == "R" else np.cross(y, r))


def rest_axes(bones, rig, side):
    """`hand_axes` of one hand of a rig, in the hand bone's own rest frame. `bones`: the armature's rest bones by name
    (each with head_local and matrix_local), `rig`: skeleton.Rig, `side` "L" / "R". The thumb is the profile's
    (`finger_chains`), else the finger whose first bone points farthest off the hand's direction. None without fingers."""
    hand = rig.prof.bone("hand", side); R = np.array(bones[hand].matrix_local.to_3x3().normalized()); y = R[:, 1]
    roots = sorted({r for b, r in rig.finger_root.items() if rig.bone_side(b) == side and r in bones})
    if len(roots) < 2: return None
    chain = rig.prof.finger_chains(side).get("thumb")
    off = {r: float(np.array(bones[r].matrix_local.to_3x3().normalized())[:, 1] @ y) for r in roots}
    thumb = rig.finger_root.get(chain[0]) if chain and chain[0] in rig.finger_root else min(off, key=off.get)
    ax = hand_axes(y, np.array(bones[thumb].head_local), [np.array(bones[r].head_local) for r in roots if r != thumb], side)
    return None if ax is None else (R.T @ ax[0], R.T @ ax[1])


def neutral(fore_rest, hand_rest, fore, hand):
    """The hand's rotation against its forearm with the rest pose taken out [..., 3, 3], in the hand bone's rest frame:
    identity = the wrist as the rig was built (its neutral)."""
    fore_rest, hand_rest = np.asarray(fore_rest, float), np.asarray(hand_rest, float)
    return np.swapaxes(np.asarray(fore, float) @ fore_rest.T @ hand_rest, -1, -2) @ np.asarray(hand, float)


def split(rel, radial, palm):
    """`rel` [..., 3, 3] from `neutral`, the hand's axes from `hand_axes` in the same frame -> (flexion, deviation) in deg:
    flexion + toward the palm (- = extension), deviation + toward the thumb (radial, - = ulnar, the little finger).
    The bend (the angle between the hand and the forearm's line) is shared out by the direction it goes in, so
    flexion^2 + deviation^2 = bend^2 and neither blows up when the hand is far off the line."""
    v = np.asarray(rel, float)[..., :, 1]; f, r = v @ np.asarray(palm, float), v @ np.asarray(radial, float)
    s = np.hypot(f, r); k = np.degrees(np.arctan2(s, v @ Y)) / np.maximum(s, 1e-12)
    return f * k, r * k
