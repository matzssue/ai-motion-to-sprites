"""One-handed swing: keep the weapon's path, solve the arm that holds it again.
Use when: the weapon's path through the clip is accepted but the arm holding it is wrung: the upper arm turned about its
    own axis, the elbow up beside the shoulder, the forearm rolled over. List it before `one_hand_weapon` in `recipe`.
Not for: a path that is itself wrong (the path is kept; `path_edits` only tilt or move it on named frames), two-handed
    grips, a rig whose arm bones do not point at the next joint, an arm that never bends in the clip.
Inputs: motion file `recipe` entry: `tip` (the weapon's tip) and `edge` (a direction across the blade toward a cutting
    edge), both in weapon mesh coordinates; `hand`, `in_hand`, `grip` as in one_hand_weapon (read from that entry of the
    same file when left out); optional `loop`, `path_edits`, `pin`, `ease_frames`, `path_hold`, `other_arm_blend`,
    `wrist`, `targets`, `weights`, `grid` (below).
Output: the clip GLB with that side's shoulder, upper arm, forearm and hand keyed on every frame of the action;
    `<out>_recipe.json`. The body, the head and the fingers stay as the clip has them; the other arm too, unless
    `other_arm_blend` is given.
Checks: per whole frame, reported and not scored: upper-arm twist, forearm roll, wrist twist, flexion and deviation,
    elbow (before and after, against `targets`), and how far the weapon ends up off its path. It does not look at
    the weapon or the arm going into the body: one_hand_weapon and the audit do.

blender -b --python pipeline/recipes/swing_arm.py -- --glb merged.glb --motion <motion>.json --out out.glb [--skeleton X]

Per frame the grip (a point and the blade direction) is read from the clip. The arm is two bones from the shoulder joint
to the wrist; free are the elbow's swivel about the shoulder-wrist line and the weapon's roll about its blade (the blade
direction stays; a double edge makes roll and roll + 180 the same weapon). Each (swivel, roll) costs what the joints
do against `targets`; where the tip is fast an edge is asked to lead. The cheapest sequence over the clip is found by
dynamic programming (closed for `loop`), smoothed once, then the forearm's roll is chosen the same way. The shoulder
bone turns only on frames where the grip is out of the arm's reach.
`path_edits`: [{"frames": {"12": 1, "11": 0.66}, "move_cm": 20, "tilt_deg": 0, "tilt_toward": [0, -1, 0]}]: on those
    frames (weight 0-1) the grip moves `move_cm` toward the point half-way between the shoulder joint and the top of
    the head (bends a straight arm at the wind-up) and the blade tilts `tilt_deg` toward a world direction.
Joining the next clip, and a changed weapon or hold:
`pin`: [0]: frames of the action that keep the clip's own arm (its swivel, no weapon roll, the four bones as they
    are): the frame an idle shares with this action. The sequence is solved through them.
`path_hold`: {"in_hand": ..., and `grip`, `tip`, `edge` when the weapon changed too}: how the weapon sat in the hand
    when the clip was made. The path is read with that hold and the arm is solved for this entry's own: the blade keeps
    its accepted path under a new weapon or a new hold. A pinned frame keeps the arm, so its weapon is off the path.
`ease_frames`: 5: over that many frames on both sides of a pinned frame the path eases from the weapon as the pinned
    arm really holds it into itself (smoothstep; turned about the grip point, the grip point along a line).
`other_arm_blend`: {"action": "idle", "frame": 0, "frames": 4, "clip": "idle.glb"}: on the first and last `frames` + 1
    frames the other arm (shoulder to hand, or `bones`) turns toward its pose on that frame of that action, fully on
    the first and the last frame. `clip` left out: the action is in the file being solved (character.py's merged file).
`wrist`: "cone" (default): the wrist's bend is costed as one cone (`targets.wrist_bend`), whatever its direction.
    "split", an option: flexion / extension and deviation to a side are costed each against its own small target
    (`targets.wrist_flexion`, `wrist_deviation`), so the fist does not hang sideways under the forearm. Off by
    default: where the path leaves no arm with the hand in line it moves the bend into the wrist's twist, up to
    100 deg (knight fr. 27: deviation 85 -> 16, twist 64 -> 100); those frames are the path's to fix.
    `weights.elbow_straight` (default 0, try 1 with "split"): a cost for an elbow opened past `targets.elbow_angle`.
`targets` (deg, cm), `weights`, `grid` (deg): TARGETS, WEIGHTS, GRID below; a key given replaces that one number.
Run it on the clip, as chain.py and character.py do: on its own output `path_edits` would move the path a second time.
The rest pose faces -Y with Z up (Blender), as everywhere in the pipeline."""
import json
import os
import sys

import numpy as np

NAME = "swing_arm"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
import wrist   # noqa: E402
from recipe_list import entries, entry   # noqa: E402

# comfort targets: past one the cost grows 10x faster (OVER); they are what the solver aims for, not the audit's limits
# wrist_flexion / wrist_deviation: costed in place of the one cone wrist_bend only with `"wrist": "split"`
# (lib/wrist.py). elbow_angle: past it the arm is locking straight; costs only with weights.elbow_straight > 0
TARGETS = {"upper_arm_twist": 45, "forearm_roll": 80, "wrist_twist": 60, "wrist_bend": 85, "elbow_above_cm": 5,
           "wrist_flexion": 35, "wrist_deviation": 15, "elbow_angle": 160}
WEIGHTS = {"upper_arm_twist": 1, "forearm_roll": 1.5, "wrist": 3, "elbow_up": 1, "elbow_across": 1, "out_of_reach": 1, "elbow_straight": 0,
           "shoulder": 0.5, "edge": 2, "swivel_step": 0.4, "roll_step": 0.05, "forearm_step": 0.02}
GRID = {"swivel": 10, "roll": 15, "forearm": 5}
OVER = 10
CUT_SHARE = 0.6        # the tip faster than this share of its top speed is cutting: an edge should lead
SHOULDER_MAX = 15.0    # deg the shoulder bone may turn toward a grip out of reach, in 2.5 deg steps (C["shoulder_max"])
BENT = 30.0            # deg of elbow flex from which a frame shows the elbow's hinge
FORWARD, UP = np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])
X, Y, Z = np.eye(3)
KEYS = ("upper_arm_twist", "forearm_roll", "wrist_twist", "wrist_bend")
SPLIT = ("wrist_flexion", "wrist_deviation")   # measured and costed in place of wrist_bend when the hand's axes are known


def unit(v):
    v = np.asarray(v, float); return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def skew(v):
    v = np.asarray(v, float); K = np.zeros(v.shape[:-1] + (3, 3))
    K[..., 0, 1], K[..., 0, 2], K[..., 1, 0] = -v[..., 2], v[..., 1], v[..., 2]
    K[..., 1, 2], K[..., 2, 0], K[..., 2, 1] = -v[..., 0], -v[..., 1], v[..., 0]
    return K


def rot(axis, deg):
    """Rotation matrices [..., 3, 3] about `axis` [..., 3] by `deg` [...]."""
    a = np.radians(np.asarray(deg, float))[..., None, None]; K = skew(unit(axis))
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * (K @ K)


def arc(a, b):
    """Shortest rotation that takes unit vectors `a` onto `b`."""
    K = skew(np.cross(a, b)); c = np.sum(a * b, -1)[..., None, None]
    return np.eye(3) + K + K @ K / np.maximum(1 + c, 1e-9)


def T(m): return np.swapaxes(m, -1, -2)


def twist_bend(R):
    """A joint's rotation since rest [..., 3, 3] -> (twist about the bone's own Y axis, signed; the bend left over), deg:
    what motion_audit's joint_angles measures."""
    R = np.asarray(R, float); tr = R[..., 0, 0] + R[..., 1, 1] + R[..., 2, 2]
    w = np.sqrt(np.maximum(1 + tr, 0)) / 2; y = np.sqrt(np.maximum(1 - R[..., 0, 0] + R[..., 1, 1] - R[..., 2, 2], 0)) / 2
    y = np.where(R[..., 0, 2] - R[..., 2, 0] < 0, -y, y)
    return np.degrees(2 * np.arctan2(y, w)), np.degrees(2 * np.arccos(np.minimum(np.sqrt(w * w + y * y), 1.0)))


def fold(d): return (np.asarray(d, float) + 180) % 360 - 180


def grip_frame(in_hand, grip, tip, edge):
    """(4x4 grip frame in the hand bone's frame: origin mid-grip, Z along the blade, X toward the edge; blade length)
    from the weapon mesh's placement `in_hand` and points of the weapon mesh."""
    M = np.asarray(in_hand, float); mid = np.mean(np.asarray(grip, float), 0); b = M[:3, :3] @ (np.asarray(tip, float) - mid)
    z = unit(b); x = M[:3, :3] @ np.asarray(edge, float); x = x - z * (x @ z)
    if np.linalg.norm(b) < 1e-9 or np.linalg.norm(x) < 1e-9: raise ValueError("`tip` lies on the grip, or `edge` runs along the blade")
    x = unit(x); G = np.eye(4); G[:3, 0], G[:3, 1], G[:3, 2], G[:3, 3] = x, np.cross(z, x), z, M[:3, :3] @ mid + M[:3, 3]
    return G, float(np.linalg.norm(b))


def weapon_inputs(motion):
    """This recipe's entry with `hand`, `in_hand` and `grip` filled in from the same file's one_hand_weapon entry."""
    P = dict(entry(motion, NAME)); other = next((e for e in entries(motion) if e.get("name") == "one_hand_weapon"), {})
    for k in ("hand", "in_hand", "grip"):
        if k not in P and k in other: P[k] = other[k]
    missing = [k for k in ("in_hand", "grip") if k not in P]
    if missing: raise ValueError("recipe %s: no %s (give them here or list a one_hand_weapon entry that has them)" % (NAME, ", ".join(missing)))
    return P


def basis_down(D):
    """Two unit vectors across the shoulder-wrist line `D`: `u` as far down as it goes (forward when D is vertical)."""
    u = -UP + D * (D @ UP)[..., None]; alt = FORWARD - D * (D @ FORWARD)[..., None]
    u = unit(np.where(np.linalg.norm(u, axis=-1, keepdims=True) < 1e-4, alt, u)); return u, np.cross(D, u)


def hinge_axis(Bu, S, E, W):
    """The elbow's hinge in the upper arm's own frame, from the frames where the elbow is bent; None when it never is."""
    yu, yf = unit(E - S), unit(W - E); flex = np.degrees(np.arccos(np.clip(np.sum(yu * yf, -1), -1, 1))); h = np.zeros(3); n = 0
    for f in np.where(flex > BENT)[0]:
        v = Bu[f].T @ unit(np.cross(yu[f], yf[f])); h += v if not h.any() or v @ h > 0 else -v; n += 1
    if not n: return None, 0
    h = h / n; return unit(h - Y * (h @ Y)), n


def swivel(S, E, W):
    """The elbow's swivel about the shoulder-wrist line [frames], deg; 0 = as far down as it goes."""
    D = unit(W - S); u, v = basis_down(D); e = (E - S) - D * np.sum((E - S) * D, -1, keepdims=True)
    return np.degrees(np.arctan2(np.sum(e * v, -1), np.sum(e * u, -1)))


def flex_dev(C, Bf, H3):
    """(flexion, deviation) of the wrist, deg (wrist.split): hand rotations `H3` under forearm rotations `Bf` [..., 3, 3]."""
    return wrist.split(T(Bf @ C["R_fh"]) @ H3, C["radial"], C["palm"])


def elbow_angle(S, E, W):
    """Angle at the elbow between the upper arm and the forearm, deg: 180 = a straight arm."""
    return np.degrees(np.arccos(np.clip(np.sum(unit(S - E) * unit(W - E), -1), -1, 1)))


def measure(C, Bs, Bu, Bf, Bh, S, E, W, head):
    """What each frame's arm does [frames]: the four joint angles (deg), elbow above the shoulder joint (cm), swivel (deg)
    and whether the wrist is above the top of the head."""
    out = {"upper_arm_twist": twist_bend(T(Bs @ C["R_su"]) @ Bu)[0], "forearm_roll": twist_bend(T(Bu @ C["R_uf"]) @ Bf)[0]}
    out["wrist_twist"], out["wrist_bend"] = twist_bend(T(Bf @ C["R_fh"]) @ Bh)
    out["swivel"] = swivel(S, E, W); out["elbow_angle"] = elbow_angle(S, E, W)
    if "radial" in C: out["wrist_flexion"], out["wrist_deviation"] = flex_dev(C, Bf, Bh)
    out["elbow_above_cm"] = (E - S) @ UP * 100; out["hand_high"] = (W - head) @ UP > 0
    return out


def solve(C, fr, phi, roll, turn=None):
    """The arm of one frame for swivels `phi` and weapon rolls `roll` (deg, [states]). `fr`: that frame's grip (G3, Gt),
    shoulder bone (c0 its head, Bs its rotation), shoulder joint s0 and how far the shoulder bone turns."""
    phi, roll = np.atleast_1d(np.asarray(phi, float)), np.atleast_1d(np.asarray(roll, float))
    turn = fr["turn"] if turn is None else turn; L1, L2 = C["L1"], C["L2"]
    H3 = fr["G3"] @ rot(Z, roll) @ C["grip3"].T; W = fr["Gt"] - H3 @ C["grip_t"]
    S = np.broadcast_to(fr["s0"], W.shape); Bs = np.broadcast_to(fr["Bs"], H3.shape)
    if turn:
        Rc = rot(np.cross(fr["Bs"][:, 1], W - fr["c0"]), turn); S = fr["c0"] + Rc @ (fr["s0"] - fr["c0"]); Bs = Rc @ fr["Bs"]
    d = np.linalg.norm(W - S, axis=-1); D = (W - S) / d[:, None]
    dc = np.clip(d, abs(L1 - L2) + 1e-3, L1 + L2 - 1e-3); short = np.abs(dc - d); W = S + D * dc[:, None]; d = dc
    u, v = basis_down(D); p = np.radians(phi)[:, None]; e = u * np.cos(p) + v * np.sin(p)
    ca = (d * d + L1 * L1 - L2 * L2) / (2 * d); E = S + D * ca[:, None] + e * np.sqrt(np.maximum(L1 * L1 - ca * ca, 0))[:, None]
    Yw, Fw = unit(E - S), unit(W - E); h = unit(np.cross(e, D)); h = unit(h - Yw * np.sum(h * Yw, -1, keepdims=True))
    Bu = np.stack([h, Yw, np.cross(h, Yw)], -1) @ C["hinge"].T
    Bc = Bu @ C["R_uf"]; Bf0 = arc(Bc[..., :, 1], Fw) @ Bc   # the forearm by the hinge alone, before its own roll
    return {"S": S, "E": E, "W": W, "H3": H3, "Bs": Bs, "Bu": Bu, "Bf0": Bf0, "short": short, "e": e, "turn": turn}


def forearm(C, s, rho):
    """Forearm roll `rho` [rolls] on top of the hinge-only forearm: (rotation, forearm roll, wrist twist, wrist bend), [states, rolls]."""
    Bf = s["Bf0"][:, None] @ rot(Y, np.asarray(rho, float))[None]
    pr = twist_bend(T(s["Bu"] @ C["R_uf"])[:, None] @ Bf)[0]; wt, wb = twist_bend(T(Bf @ C["R_fh"]) @ s["H3"][:, None])
    return Bf, pr, wt, wb


def soft(x, target): return (x / target) ** 2 + OVER * np.maximum(0.0, np.abs(x) / target - 1) ** 2


def roll_cost(C, pr, wt, wb, fd=None):
    """What the forearm's roll and the wrist cost. `fd` (flexion, deviation): the wrist's bend by direction, each against its
    own target, in place of the one cone `wb`."""
    t, w = C["targets"], C["weights"]
    bend = soft(wb, t["wrist_bend"]) if fd is None else soft(fd[0], t["wrist_flexion"]) + soft(fd[1], t["wrist_deviation"])
    return w["forearm_roll"] * soft(pr, t["forearm_roll"]) + w["wrist"] * (soft(wt, t["wrist_twist"]) + bend)


def forearm_cost(C, s, rho):
    """`roll_cost` of the forearm rolls `rho` on the states `s` [states, rolls]."""
    Bf, pr, wt, wb = forearm(C, s, rho)
    return roll_cost(C, pr, wt, wb, flex_dev(C, Bf, s["H3"][:, None]) if C.get("wrist_split") else None)


def cost(C, fr, s):
    """What each state's arm costs [states]: joints against the targets, the elbow up beside the shoulder or across the
    chest, a grip out of reach, a turned shoulder bone."""
    t, w = C["targets"], C["weights"]
    c = w["upper_arm_twist"] * soft(twist_bend(T(s["Bs"] @ C["R_su"]) @ s["Bu"])[0], t["upper_arm_twist"])
    c = c + forearm_cost(C, s, np.arange(-180, 180, 10)).min(1)
    if w.get("elbow_straight") and "elbow_angle" in t:   # an arm locked straight: the weapon's roll can pull the wrist back in
        c = c + w["elbow_straight"] * (np.maximum(0.0, elbow_angle(s["S"], s["E"], s["W"]) - t["elbow_angle"]) / 10) ** 2
    up = (s["E"] - s["S"]) @ UP / C["L1"]; high = (s["W"] - fr["head"]) @ UP > 0
    c = c + np.where((up > 0) & ~high, w["elbow_up"] * up * up * 10, 0)
    em = np.sum(s["e"] * unit(fr["other"] - s["S"]), -1); ef = s["e"] @ FORWARD
    c = c + np.where(em > 0.2, w["elbow_across"] * (em - 0.2) ** 2 * 10, 0)
    c = c + np.where((ef > 0.4) & (s["e"] @ UP > 0), w["elbow_across"] * (ef - 0.4) * 10, 0)
    return c + w["out_of_reach"] * s["short"] * 100 + w["shoulder"] * (s["turn"] / 10) ** 2


def edit_path(G3, Gt, s0, head, edits):
    """The grip path [frames] after `path_edits`: the blade tilted toward a world direction about the grip point, the grip
    moved toward the point half-way between the shoulder joint and the top of the head."""
    G3, Gt = G3.copy(), Gt.copy()
    for e in edits or []:
        for fs, wgt in e["frames"].items():
            f = int(fs)
            if not 0 <= f < len(Gt): raise ValueError("path_edits: frame %d is outside the action (0-%d)" % (f, len(Gt) - 1))
            ax = np.cross(G3[f][:, 2], unit(e.get("tilt_toward", FORWARD)))
            if np.linalg.norm(ax) > 1e-6 and e.get("tilt_deg"): G3[f] = rot(ax, wgt * e["tilt_deg"]) @ G3[f]
            Gt[f] = Gt[f] + unit(s0[f] + (head[f] - s0[f]) * 0.5 - Gt[f]) * wgt * e.get("move_cm", 0) / 100
    return G3, Gt


def turn_of(R):
    """(angle in deg, axis) of a rotation matrix; a turn of nothing gets the X axis."""
    ax = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))), unit(ax) if np.linalg.norm(ax) > 1e-9 else X


def smoothstep(x): return x * x * (3 - 2 * x)


def ease_path(G3, Gt, real3, realt, pins, ease, loop):
    """The path [frames] around pinned frames. A pinned frame keeps the clip's arm, so its weapon is where that arm holds it
    (`real3`, `realt`): off the path when the hold changed. That pose becomes the pinned frame's target, and on the
    `ease` - 1 frames on both sides the path is turned and moved toward it: smoothstep weight, the turn about the grip
    point, the grip point along a straight line. -> (G3, Gt, {pin: (deg, cm) the weapon is off the path there})."""
    G3, Gt = G3.copy(), Gt.copy(); N = len(Gt) - 1; off = {}
    for p in pins:
        ang, ax = turn_of(real3[p] @ G3[p].T); dT = realt[p] - Gt[p]; off[p] = (ang, float(np.linalg.norm(dT)) * 100)
        G3[p], Gt[p] = real3[p], realt[p]
        for k in range(1, ease):
            s = 1 - smoothstep(k / ease)
            for f in ({(p + k) % N, (p - k) % N} if loop else {p + k, p - k}):
                if 0 <= f <= N and f not in pins: G3[f] = rot(ax, ang * s) @ G3[f]; Gt[f] = Gt[f] + dT * s
    if loop and 0 in pins: G3[N], Gt[N] = real3[N], realt[N]   # the last frame repeats the first: the clip's arm too
    return G3, Gt, off


def end_weights(n, k):
    """Weight per frame [n] of a pose blended in at both ends of an action: 1 on the first and the last frame, smoothstep
    down to 0 on the frame `k` + 1 away."""
    d = np.minimum(np.arange(n), n - 1 - np.arange(n)); return np.where(d <= k, smoothstep(1 - d / (k + 1.0)), 0.0)


def cheapest(U, step, start=None):
    """Cheapest sequence of states through the unary costs U [frames, states] with the cost `step` [states, states] between
    neighbours; with `start` it begins there and pays the step back to it (a loop). -> (total, [state per frame])."""
    n = U.shape[1]; acc = U[0].copy() if start is None else np.where(np.arange(n) == start, U[0], np.inf); back = []
    for f in range(1, len(U)):
        m = acc[:, None] + step; b = m.argmin(0); back.append(b); acc = m[b, np.arange(n)] + U[f]
    if start is not None: acc = acc + step[:, start]
    s = int(acc.argmin()); total = float(acc[s]); path = [s]
    for b in reversed(back): s = int(b[s]); path.append(s)
    return total, path[::-1]


def cheapest_loop(U, step, loop):
    """`cheapest`, closed into a loop from the best of the 12 cheapest first states."""
    return min((cheapest(U, step, int(s)) for s in np.argsort(U[0], kind="stable")[:12]), key=lambda x: x[0]) if loop else cheapest(U, step)


def wrapped(a, unit_deg): a = np.asarray(a, float); return np.abs(fold(a[:, None] - a[None, :])) / unit_deg


def smooth(deg, loop):
    a = np.unwrap(np.radians(deg)); k = np.array([0.25, 0.5, 0.25])
    if loop: a = np.convolve(np.r_[a[-1], a, a[0]], k, "valid")
    else: a[1:-1] = np.convolve(a, k, "valid")
    return np.degrees(a)


def plan(clip, C, loop=True, edits=None, pins=(), ease=0):
    """The arm for every frame of the clip. `clip`: arrays over the frames of the action (first and last included): the grip
    G3 [n, 3, 3] / Gt [n, 3], the shoulder bone c0, Bs, the shoulder joint s0, the top of the head `head`, the other
    shoulder joint `other`. `C`: the arm's constants (rest rotations R_su, R_uf, R_fh, lengths L1, L2, hinge, grip3,
    grip_t, blade, targets, weights, grid). `pins`: frames that keep the clip's arm, which `clip` then holds too (Bu, Bf,
    Bh, E, W); `ease`: see ease_path. -> per-frame arrays: Bs, Bu, Bf, Bh, S, E, W (the pose), swivel, roll, forearm,
    turn, short, cut, pinned, G3, Gt (the path asked for), and `held` (ease_path's offsets)."""
    n = len(clip["Gt"]); F = n - 1 if loop else n; g = C["grid"]; w = C["weights"]
    if any(not 0 <= int(p) < n for p in pins): raise ValueError("pin: frames %s are outside the action (0-%d)" % (sorted(pins), n - 1))
    pins = sorted({int(p) % F for p in pins}); held = {}
    G3, Gt = edit_path(clip["G3"], clip["Gt"], clip["s0"], clip["head"], edits)
    if pins:
        G3, Gt, held = ease_path(G3, Gt, clip["Bh"] @ C["grip3"], clip["W"] + clip["Bh"] @ C["grip_t"], pins, ease, loop)
        sw_in = swivel(clip["s0"], clip["E"], clip["W"])
    frs = [dict({k: clip[k][f] for k in ("c0", "s0", "Bs", "head", "other")}, G3=G3[f], Gt=Gt[f], turn=0.0) for f in range(n)]
    tip = Gt + G3[:, :, 2] * C["blade"]; a_, b_ = np.arange(n) - 1, np.arange(n) + 1
    vel = (tip[b_ % (n - 1) if loop else np.minimum(b_, n - 1)] - tip[a_ % (n - 1) if loop else np.maximum(a_, 0)]) / 2
    speed = np.linalg.norm(vel, axis=1); cut = speed > CUT_SHARE * speed.max()
    for fr in frs[:F]:   # the shoulder bone turns only as far as it takes to reach the grip
        while solve(C, fr, 0, 0)["short"][0] > 1e-4 and fr["turn"] < C.get("shoulder_max", SHOULDER_MAX): fr["turn"] += 2.5
    PH, RL = np.arange(-180, 180, g["swivel"]), np.arange(-180, 180, g["roll"])
    P, R = np.repeat(PH, len(RL)).astype(float), np.tile(RL, len(PH)).astype(float); U = np.zeros((F, len(P)))
    for f, fr in enumerate(frs[:F]):
        U[f] = cost(C, fr, solve(C, fr, P, R))
        v = vel[f] - G3[f][:, 2] * (vel[f] @ G3[f][:, 2])
        if cut[f] and np.linalg.norm(v) > 1e-6: U[f] += w["edge"] * (1 - np.abs((G3[f] @ rot(Z, R))[:, :, 0] @ unit(v)))
    for p in pins:   # only the state nearest the clip's arm: its swivel, no roll
        j = int(np.argmin(np.abs(fold(P - sw_in[p])) + np.abs(fold(R)))); U[p] = np.inf; U[p, j] = 0.0
    step = w["swivel_step"] * wrapped(P, g["swivel"]) ** 2 + w["roll_step"] * wrapped(R, 15.0) ** 2
    path = cheapest_loop(U, step, loop)[1]; phi, roll = smooth(P[path], loop), smooth(R[path], loop)
    for p in pins: phi[p], roll[p] = sw_in[p], 0.0
    sols = [solve(C, frs[f], phi[f], roll[f]) for f in range(F)]
    RHO = np.arange(-180, 180, g["forearm"]).astype(float)   # its own pass, so the forearm never flips through +-180 between frames
    U2 = np.array([forearm_cost(C, s, RHO)[0] for s in sols])
    rho_in = {p: float(twist_bend(sols[p]["Bf0"][0].T @ clip["Bf"][p])[0]) for p in pins}   # the clip's forearm as a roll
    for p, r in rho_in.items(): U2[p] = np.inf; U2[p, int(np.argmin(np.abs(fold(RHO - r))))] = 0.0
    rho = RHO[cheapest_loop(U2, w["forearm_step"] * wrapped(RHO, 5.0) ** 2, loop)[1]]
    for p, r in rho_in.items(): rho[p] = r
    ii = np.arange(n) % F; out = {k: np.array([sols[i][k][0] for i in ii]) for k in ("S", "E", "W", "Bs", "Bu", "short")}
    out["Bh"] = np.array([sols[i]["H3"][0] for i in ii]); out["Bf"] = np.array([forearm(C, sols[i], rho[i:i + 1])[0][0, 0] for i in ii])
    pinned = np.isin(ii, pins)
    for k, src in (("S", "s0"), ("E", "E"), ("W", "W"), ("Bs", "Bs"), ("Bu", "Bu"), ("Bf", "Bf"), ("Bh", "Bh")):
        if pins: out[k][pinned] = clip[src][pinned]
    out["short"][pinned] = 0
    out.update(swivel=phi[ii], roll=roll[ii], forearm=rho[ii], turn=np.array([frs[i]["turn"] for i in ii]), cut=cut, G3=G3, Gt=Gt,
               pinned=pinned, held=held)
    return out


def wrist_mode(P):
    """How a recipe entry wants the wrist costed: "cone" unless it asks for "split"."""
    return P.get("wrist", "cone")


def over_targets(m, targets, split=False):
    """Per frame, the names of what is over its comfort target; the elbow counts only with the wrist below the top of the head.
    `split`: the wrist's flexion and deviation count in place of its one cone."""
    keys = [k for k in KEYS if k != "wrist_bend"] + list(SPLIT) if split else KEYS
    out = [[k for k in keys if abs(m[k][f]) > targets[k]] for f in range(len(m["swivel"]))]
    for f in np.where((m["elbow_above_cm"] > targets["elbow_above_cm"]) & ~m["hand_high"])[0]: out[f].append("elbow_above_cm")
    return out


def summary(rows):
    """Per-frame rows [{"frame", "before": {...}, "after": {...}, "over", "grip_off_cm", "blade_off_deg", "short_cm"}]
    -> the report's numbers and its one line."""
    mx = lambda w, k: round(max(abs(r[w][k]) for r in rows))   # noqa: E731
    bad = [r["frame"] for r in rows if r["over"]]; short = [r["frame"] for r in rows if r["short_cm"] > 0]
    keys = KEYS + tuple(k for k in SPLIT if k in rows[0]["after"])
    out = {"frames": len(rows), "max": {w: {k: mx(w, k) for k in keys} for w in ("before", "after")},
           "elbow_above_cm": {w: round(max(r[w]["elbow_above_cm"] for r in rows), 1) for w in ("before", "after")},
           "over_targets": bad, "out_of_reach": short,
           "off_path": {"grip_cm": max(r["grip_off_cm"] for r in rows), "blade_deg": max(r["blade_off_deg"] for r in rows)}}
    out["line"] = ("arm solved again under the weapon path: " + ", ".join("%s %d -> %d" % (
        k.replace("_", " "), out["max"]["before"][k], out["max"]["after"][k]) for k in keys) + " deg; over a comfort target on %d of %d frames; "
        "weapon off its path up to %.1f cm / %.1f deg%s") % (len(bad), len(rows), out["off_path"]["grip_cm"], out["off_path"]["blade_deg"],
                                                              ", out of reach on %d frames" % len(short) if short else "")
    return out


def main():
    import argparse

    import bpy
    from mathutils import Matrix
    from collisions import rig_of

    ap = argparse.ArgumentParser(description="Solve the weapon arm again under the weapon's own path.")
    ap.add_argument("--glb", required=True); ap.add_argument("--motion", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--skeleton", default=None)
    A = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
    R = json.load(open(A.motion, encoding="utf-8"))
    try:
        P = weapon_inputs(R); GRIP, blade = grip_frame(P["in_hand"], P["grip"], P["tip"], P["edge"]); PH = P.get("path_hold")
        PATH = grip_frame(PH["in_hand"], PH.get("grip", P["grip"]), PH.get("tip", P["tip"]), PH.get("edge", P["edge"]))[0] if PH else GRIP
    except ValueError as e:
        raise SystemExit("%s: %s" % (A.motion, e))
    side = P.get("hand", "right").capitalize(); oside = "Left" if side == "Right" else "Right"; loop = P.get("loop", True)
    OB = P.get("other_arm_blend"); target = {}

    def take(path, action):
        """The armature of a GLB with `action` on it, every bone without a curve there at rest."""
        if path: bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
        arm = next(o for o in bpy.data.objects if o.type == "ARMATURE"); act = bpy.data.actions.get(action)
        if act is None: raise SystemExit("%s: no action %s (there are: %s)" % (path or A.glb, action, ", ".join(sorted(a.name for a in bpy.data.actions))))
        arm.animation_data.action = act
        try: arm.animation_data.action_slot = act.slots[0]
        except (AttributeError, IndexError): pass
        for pb in arm.pose.bones: pb.matrix_basis = Matrix()   # bones without curves here keep another action's pose
        return arm, act

    def other_pose(path):
        """The other arm's bones -> their own rotation on the frame of the action `other_arm_blend` names."""
        arm, _ = take(path, OB["action"]); prof = rig_of(arm, A.skeleton).prof
        bones = OB.get("bones") or [prof.bone(r, oside) for r in ("shoulder", "upper_arm", "forearm", "hand") if prof.has(r, oside)]
        missing = [b for b in bones if b not in arm.pose.bones]
        if missing: raise SystemExit("%s: other_arm_blend.bones: no bone %s in %s" % (A.motion, ", ".join(missing), path or A.glb))
        bpy.context.scene.frame_set(int(OB.get("frame", 0))); bpy.context.view_layer.update()
        return {b: arm.pose.bones[b].matrix_basis.to_quaternion() for b in bones}

    if OB and OB.get("clip"):
        other_clip = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(A.motion)), OB["clip"]))
        if not os.path.exists(other_clip): raise SystemExit("%s: other_arm_blend.clip: no file %s" % (A.motion, other_clip))
        target = other_pose(other_clip)
    arm, act = take(A.glb, R["action"]); sc = bpy.context.scene
    if OB and not OB.get("clip"): target = other_pose(None); arm, act = take(None, R["action"])
    RIG = rig_of(arm, A.skeleton); PROF = RIG.prof; pbs, dbs = arm.pose.bones, arm.data.bones
    UA, FA, HA = (PROF.bone(r, side) for r in ("upper_arm", "forearm", "hand")); HEAD = PROF.bone("head")
    OTHER = PROF.bone("upper_arm", oside)
    if dbs[UA].parent is None: raise SystemExit("%s: the upper arm %s has no parent bone to measure its twist against" % (A.glb, UA))
    CL = dbs[UA].parent.name; turn_ok = PROF.has("shoulder", side) and PROF.bone("shoulder", side) == CL
    AW = np.array(arm.matrix_world); scale = float(abs(np.linalg.det(AW[:3, :3])) ** (1 / 3)); RW = AW[:3, :3] / scale
    f0, f1 = (int(round(x)) for x in act.frame_range); frames = list(range(f0, f1 + 1))

    def rest(n): return RW @ np.array(dbs[n].matrix_local.to_3x3().normalized())
    def point(v): return AW[:3, :3] @ np.array(v) + AW[:3, 3]

    def read():
        """World pose of the arm on every frame: rotations (unit) and joints of the four bones, head top, other shoulder."""
        out = {k: [] for k in ("Bs", "Bu", "Bf", "Bh", "c0", "s0", "E", "W", "head", "other")}
        for f in frames:
            sc.frame_set(f); bpy.context.view_layer.update()
            for k, n in (("Bs", CL), ("Bu", UA), ("Bf", FA), ("Bh", HA)): out[k].append(RW @ np.array(pbs[n].matrix.to_3x3().normalized()))
            for k, n in (("c0", CL), ("s0", UA), ("E", FA), ("W", HA), ("other", OTHER)): out[k].append(point(pbs[n].head))
            out["head"].append(point(pbs[HEAD].tail))
        return {k: np.array(v) for k, v in out.items()}

    I = read()
    C = {"R_su": rest(CL).T @ rest(UA), "R_uf": rest(UA).T @ rest(FA), "R_fh": rest(FA).T @ rest(HA),
         "L1": float(np.linalg.norm(point(dbs[FA].head_local) - point(dbs[UA].head_local))),
         "L2": float(np.linalg.norm(point(dbs[HA].head_local) - point(dbs[FA].head_local))),
         "grip3": GRIP[:3, :3], "grip_t": GRIP[:3, 3] * scale, "path3": PATH[:3, :3], "path_t": PATH[:3, 3] * scale, "blade": blade * scale,
         "targets": dict(TARGETS, **P.get("targets", {})), "weights": dict(WEIGHTS, **P.get("weights", {})), "grid": dict(GRID, **P.get("grid", {}))}
    hinge, bent = hinge_axis(I["Bu"], I["s0"], I["E"], I["W"])
    if hinge is None: raise SystemExit("%s: the %s arm never bends %d deg in %s: no elbow hinge to read" % (A.glb, side.lower(), BENT, R["action"]))
    C["hinge"] = np.stack([hinge, Y, np.cross(hinge, Y)], -1)
    C["shoulder_max"] = SHOULDER_MAX if turn_ok else 0.0   # an upper arm hanging on the chest: nothing to turn toward a far grip
    axes = wrist.rest_axes(dbs, RIG, side[0]) if PROF.has("fingers", side) else None
    if axes: C["radial"], C["palm"] = axes
    C["wrist_split"] = bool(axes) and wrist_mode(P) == "split"
    if wrist_mode(P) == "split" and not axes:
        print("recipe %s: no fingers below %s to tell the hand's sides apart: the wrist is costed as one cone" % (NAME, HA))
    # the path is read with the hold the clip was made with, the arm solved for this entry's own
    clip = dict({k: I[k] for k in ("c0", "s0", "Bs", "head", "other", "Bu", "Bf", "Bh", "E", "W")}, G3=I["Bh"] @ C["path3"], Gt=I["W"] + I["Bh"] @ C["path_t"])
    try:   # path_edits and pin name frames of the action; plan() counts from its first frame
        O = plan(clip, C, loop, [dict(e, frames={int(k) - f0: v for k, v in e["frames"].items()}) for e in P.get("path_edits", [])],
                 [int(p) - f0 for p in P.get("pin", [])], int(P.get("ease_frames", 0)))
    except ValueError as e:
        raise SystemExit("%s: recipe %s: %s" % (A.motion, NAME, e))
    notes = []
    if PH: notes.append("path read with the hold the clip was made with")
    for p, (deg, cm) in sorted(O["held"].items()):
        notes.append("fr. %d pinned to the clip's arm, the weapon there %.1f deg / %.1f cm off the path%s" % (
            frames[p], deg, cm, ", eased in over %d frames" % P["ease_frames"] if P.get("ease_frames", 0) > 1 else ""))
    print("recipe %s: %s arm (%s, %s, %s, %s), hinge from %d bent frames, tip cutting on fr. %s%s" % (
        NAME, side.lower(), CL, UA, FA, HA, bent, [frames[f] for f in np.where(O["cut"])[0]],
        ", %d path edit(s)" % len(P["path_edits"]) if P.get("path_edits") else ""))

    # keys: the four bones' rotation on every frame of this action
    names = (CL, UA, FA, HA); bags = [act] if hasattr(act, "fcurves") else [b for la in act.layers for st in la.strips for b in st.channelbags]
    for bag in bags:
        for fc in [c for c in bag.fcurves if c.data_path.startswith('pose.bones["') and c.data_path.split('"')[1] in names and "rotation" in c.data_path]:
            bag.fcurves.remove(fc)
    AWi = np.linalg.inv(AW); prev = {}
    for n in names: pbs[n].rotation_mode = "QUATERNION"
    for i, f in enumerate(frames):
        sc.frame_set(f)
        for n, B3, at in ((CL, O["Bs"][i], None), (UA, O["Bu"][i], O["S"][i]), (FA, O["Bf"][i], O["E"][i]), (HA, O["Bh"][i], O["W"][i])):
            bpy.context.view_layer.update(); M = np.eye(4); M[:3, :3] = RW.T @ B3
            M[:3, 3] = AWi[:3, :3] @ at + AWi[:3, 3] if at is not None else np.array(pbs[n].matrix.translation)
            pbs[n].matrix = Matrix(M.tolist())
        bpy.context.view_layer.update()
        for n in names:
            q = pbs[n].rotation_quaternion.copy()
            if n in prev and q.dot(prev[n]) < 0: q = -q
            pbs[n].rotation_quaternion = q; prev[n] = q; pbs[n].keyframe_insert("rotation_quaternion", frame=f)
    if OB:   # the other arm toward the next clip's pose at both ends of the action
        wts = end_weights(len(frames), int(OB.get("frames", 4)))
        for i in np.where(wts > 0)[0]:
            sc.frame_set(frames[i])
            for b, q1 in target.items():
                pbs[b].rotation_mode = "QUATERNION"; q0 = pbs[b].rotation_quaternion.copy()
                pbs[b].rotation_quaternion = q0.slerp(-q1 if q0.dot(q1) < 0 else q1, float(wts[i]))
                pbs[b].keyframe_insert("rotation_quaternion", frame=frames[i])
        notes.append("other arm (%s) blended toward %s fr. %d on %d frames at each end" % (
            ", ".join(target), OB["action"], OB.get("frame", 0), int((wts > 0).sum()) // 2))

    # what came out, read back from the keyed clip
    N_ = read(); before = measure(C, I["Bs"], I["Bu"], I["Bf"], I["Bh"], I["s0"], I["E"], I["W"], I["head"])
    after = measure(C, N_["Bs"], N_["Bu"], N_["Bf"], N_["Bh"], N_["s0"], N_["E"], N_["W"], N_["head"])
    over = over_targets(after, C["targets"], C["wrist_split"]); G3n = N_["Bh"] @ C["grip3"]; Gtn = N_["W"] + N_["Bh"] @ C["grip_t"]
    off = np.linalg.norm(Gtn - O["Gt"], axis=1) * 100
    bl = np.degrees(np.arccos(np.clip(np.sum(G3n[:, :, 2] * O["G3"][:, :, 2], -1), -1, 1)))
    more = ("elbow_above_cm", "swivel", "elbow_angle") + (SPLIT if "radial" in C else ())
    vals = lambda m, i: dict({k: round(float(m[k][i]), 1) for k in KEYS + more}, hand_high=bool(m["hand_high"][i]))  # noqa: E731
    rows = [{"frame": f, "before": vals(before, i), "after": vals(after, i), "over": over[i], "grip_off_cm": round(float(off[i]), 2),
             "blade_off_deg": round(float(bl[i]), 2), "short_cm": round(float(O["short"][i]) * 100, 1),
             "weapon_roll": round(float(O["roll"][i]), 1), "shoulder_turn": float(O["turn"][i]), "cutting": bool(O["cut"][i]),
             "pinned": bool(O["pinned"][i]),
             "path_moved_cm": round(float(np.linalg.norm(O["Gt"][i] - clip["Gt"][i])) * 100, 1)} for i, f in enumerate(frames)]
    for r in rows:
        print("ARM %3d | twist %4.0f -> %4.0f | forearm roll %4.0f -> %4.0f | wrist twist %4.0f -> %4.0f, bend %4.0f -> %4.0f | elbow %+4.0f -> %+4.0f cm%s" % (
            r["frame"], *(r[w][k] for k in KEYS for w in ("before", "after")), r["before"]["elbow_above_cm"], r["after"]["elbow_above_cm"],
            " | over: " + ", ".join(r["over"]) if r["over"] else ""))
    if "radial" in C:   # + flexion / - extension, + toward the thumb / - toward the little finger; 180 = a straight arm
        for r in rows:
            print("WRIST %3d | flexion %+4.0f -> %+4.0f | deviation %+4.0f -> %+4.0f | elbow angle %4.0f -> %4.0f" % (
                r["frame"], *(r[w][k] for k in SPLIT + ("elbow_angle",) for w in ("before", "after"))))
    rep = dict({"recipe": NAME, "action": R["action"], "hand": side[0], "sets_hand": side[0], "bones": list(names)}, **summary(rows))
    rep["targets"] = C["targets"]; rep["wrist"] = "split" if C["wrist_split"] else "cone"; rep["pinned"] = [r["frame"] for r in rows if r["pinned"]]
    rep["held_off_path"] = {str(frames[p]): {"deg": round(deg, 1), "cm": round(cm, 1)} for p, (deg, cm) in O["held"].items()}
    if notes: rep["notes"] = notes; rep["line"] += "; " + "; ".join(notes)
    rep["limits"] = ("whole frames; comfort targets are the solver's aim, not the audit's limits; the weapon or the arm in the "
                     "body is not looked at here; the shoulder bone turns only for a grip out of reach")
    rep["per_frame"] = rows
    worst = max(rows, key=lambda r: 0 if r["short_cm"] else r["grip_off_cm"])
    if worst["grip_off_cm"] > 2 and not worst["short_cm"]:
        raise SystemExit("recipe %s: the solved arm leaves the weapon %.1f cm off its path on fr. %d: this rig's arm bones do not "
                         "point at the next joint" % (NAME, worst["grip_off_cm"], worst["frame"]))
    out = os.path.abspath(A.out); json.dump(rep, open(out.replace(".glb", "_recipe.json"), "w", encoding="utf-8"), indent=1)
    sc.frame_set(f0)
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_animations=True)
    print("recipe %s: %s" % (NAME, rep["line"]))
    print("RECIPE OK", out)


if __name__ == "__main__":
    main()
