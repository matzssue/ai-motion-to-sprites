"""One-handed swing: keep the weapon's path, solve the arm that holds it again.
Use when: the weapon's path through the clip is accepted but the arm holding it is wrung: the upper arm turned about its
    own axis, the elbow up beside the shoulder, the forearm rolled over. List it before `one_hand_weapon` in `recipe`.
Not for: a path that is itself wrong (the path is kept; `path_edits` only tilt or move it on named frames), two-handed
    grips, a rig whose arm bones do not point at the next joint, an arm that never bends in the clip.
Inputs: motion file `recipe` entry: `tip` (the weapon's tip) and `edge` (a direction across the blade toward a cutting
    edge), both in weapon mesh coordinates; `hand`, `in_hand`, `grip` as in one_hand_weapon (read from that entry of the
    same file when left out); optional `loop`, `path_edits`, `targets`, `weights`, `grid` (below).
Output: the clip GLB with that side's shoulder, upper arm, forearm and hand keyed on every frame of the action;
    `<out>_recipe.json`. The body, the other arm, the head and the fingers stay as the clip has them.
Checks: per whole frame, reported and not scored: upper-arm twist, forearm roll, wrist twist and bend, elbow above the
    shoulder (before and after, against `targets`), and how far the weapon ends up off its path. It does not look at
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
from recipe_list import entries, entry   # noqa: E402

# comfort targets: past one the cost grows 10x faster (OVER); they are what the solver aims for, not the audit's limits
TARGETS = {"upper_arm_twist": 45, "forearm_roll": 80, "wrist_twist": 60, "wrist_bend": 85, "elbow_above_cm": 5}
WEIGHTS = {"upper_arm_twist": 1, "forearm_roll": 1.5, "wrist": 3, "elbow_up": 1, "elbow_across": 1, "out_of_reach": 1,
           "shoulder": 0.5, "edge": 2, "swivel_step": 0.4, "roll_step": 0.05, "forearm_step": 0.02}
GRID = {"swivel": 10, "roll": 15, "forearm": 5}
OVER = 10
CUT_SHARE = 0.6        # the tip faster than this share of its top speed is cutting: an edge should lead
SHOULDER_MAX = 15.0    # deg the shoulder bone may turn toward a grip out of reach, in 2.5 deg steps (C["shoulder_max"])
BENT = 30.0            # deg of elbow flex from which a frame shows the elbow's hinge
FORWARD, UP = np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])
X, Y, Z = np.eye(3)
KEYS = ("upper_arm_twist", "forearm_roll", "wrist_twist", "wrist_bend")


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


def measure(C, Bs, Bu, Bf, Bh, S, E, W, head):
    """What each frame's arm does [frames]: the four joint angles (deg), elbow above the shoulder joint (cm), swivel (deg)
    and whether the wrist is above the top of the head."""
    out = {"upper_arm_twist": twist_bend(T(Bs @ C["R_su"]) @ Bu)[0], "forearm_roll": twist_bend(T(Bu @ C["R_uf"]) @ Bf)[0]}
    out["wrist_twist"], out["wrist_bend"] = twist_bend(T(Bf @ C["R_fh"]) @ Bh)
    D = unit(W - S); u, v = basis_down(D); e = (E - S) - D * np.sum((E - S) * D, -1, keepdims=True)
    out["swivel"] = np.degrees(np.arctan2(np.sum(e * v, -1), np.sum(e * u, -1)))
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


def roll_cost(C, pr, wt, wb):
    t, w = C["targets"], C["weights"]
    return w["forearm_roll"] * soft(pr, t["forearm_roll"]) + w["wrist"] * (soft(wt, t["wrist_twist"]) + soft(wb, t["wrist_bend"]))


def cost(C, fr, s):
    """What each state's arm costs [states]: joints against the targets, the elbow up beside the shoulder or across the
    chest, a grip out of reach, a turned shoulder bone."""
    t, w = C["targets"], C["weights"]
    c = w["upper_arm_twist"] * soft(twist_bend(T(s["Bs"] @ C["R_su"]) @ s["Bu"])[0], t["upper_arm_twist"])
    c = c + roll_cost(C, *forearm(C, s, np.arange(-180, 180, 10))[1:]).min(1)
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


def plan(clip, C, loop=True, edits=None):
    """The arm for every frame of the clip. `clip`: arrays over the frames of the action (first and last included): the grip
    G3 [n, 3, 3] / Gt [n, 3], the shoulder bone c0, Bs, the shoulder joint s0, the top of the head `head`, the other
    shoulder joint `other`. `C`: the arm's constants (rest rotations R_su, R_uf, R_fh, lengths L1, L2, hinge, grip3,
    grip_t, blade, targets, weights, grid). -> per-frame arrays: Bs, Bu, Bf, Bh, S, E, W (the pose), swivel, roll,
    forearm, turn, short, cut, G3, Gt (the path asked for)."""
    n = len(clip["Gt"]); F = n - 1 if loop else n; g = C["grid"]; w = C["weights"]
    G3, Gt = edit_path(clip["G3"], clip["Gt"], clip["s0"], clip["head"], edits)
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
    step = w["swivel_step"] * wrapped(P, g["swivel"]) ** 2 + w["roll_step"] * wrapped(R, 15.0) ** 2
    path = cheapest_loop(U, step, loop)[1]; phi, roll = smooth(P[path], loop), smooth(R[path], loop)
    sols = [solve(C, frs[f], phi[f], roll[f]) for f in range(F)]
    RHO = np.arange(-180, 180, g["forearm"]).astype(float)   # its own pass, so the forearm never flips through +-180 between frames
    U2 = np.array([roll_cost(C, *forearm(C, s, RHO)[1:])[0] for s in sols])
    rho = RHO[cheapest_loop(U2, w["forearm_step"] * wrapped(RHO, 5.0) ** 2, loop)[1]]
    ii = np.arange(n) % F; out = {k: np.array([sols[i][k][0] for i in ii]) for k in ("S", "E", "W", "Bs", "Bu", "short")}
    out["Bh"] = np.array([sols[i]["H3"][0] for i in ii]); out["Bf"] = np.array([forearm(C, sols[i], rho[i:i + 1])[0][0, 0] for i in ii])
    out.update(swivel=phi[ii], roll=roll[ii], forearm=rho[ii], turn=np.array([frs[i]["turn"] for i in ii]), cut=cut, G3=G3, Gt=Gt)
    return out


def over_targets(m, targets):
    """Per frame, the names of what is over its comfort target; the elbow counts only with the wrist below the top of the head."""
    out = [[k for k in KEYS if abs(m[k][f]) > targets[k]] for f in range(len(m["swivel"]))]
    for f in np.where((m["elbow_above_cm"] > targets["elbow_above_cm"]) & ~m["hand_high"])[0]: out[f].append("elbow_above_cm")
    return out


def summary(rows):
    """Per-frame rows [{"frame", "before": {...}, "after": {...}, "over", "grip_off_cm", "blade_off_deg", "short_cm"}]
    -> the report's numbers and its one line."""
    mx = lambda w, k: round(max(abs(r[w][k]) for r in rows))   # noqa: E731
    bad = [r["frame"] for r in rows if r["over"]]; short = [r["frame"] for r in rows if r["short_cm"] > 0]
    out = {"frames": len(rows), "max": {w: {k: mx(w, k) for k in KEYS} for w in ("before", "after")},
           "elbow_above_cm": {w: round(max(r[w]["elbow_above_cm"] for r in rows), 1) for w in ("before", "after")},
           "over_targets": bad, "out_of_reach": short,
           "off_path": {"grip_cm": max(r["grip_off_cm"] for r in rows), "blade_deg": max(r["blade_off_deg"] for r in rows)}}
    out["line"] = ("arm solved again under the weapon path: " + ", ".join("%s %d -> %d" % (
        k.replace("_", " "), out["max"]["before"][k], out["max"]["after"][k]) for k in KEYS) + " deg; over a comfort target on %d of %d frames; "
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
        P = weapon_inputs(R); GRIP, blade = grip_frame(P["in_hand"], P["grip"], P["tip"], P["edge"])
    except ValueError as e:
        raise SystemExit("%s: %s" % (A.motion, e))
    side = P.get("hand", "right").capitalize(); loop = P.get("loop", True)

    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=os.path.abspath(A.glb)); sc = bpy.context.scene
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE"); act = bpy.data.actions.get(R["action"])
    if act is None: raise SystemExit("%s: no action %s (there are: %s)" % (A.glb, R["action"], ", ".join(sorted(a.name for a in bpy.data.actions))))
    arm.animation_data.action = act
    try: arm.animation_data.action_slot = act.slots[0]
    except (AttributeError, IndexError): pass
    for pb in arm.pose.bones: pb.matrix_basis = Matrix()   # bones without curves here keep another action's pose
    PROF = rig_of(arm, A.skeleton).prof; pbs, dbs = arm.pose.bones, arm.data.bones
    UA, FA, HA = (PROF.bone(r, side) for r in ("upper_arm", "forearm", "hand")); HEAD = PROF.bone("head")
    OTHER = PROF.bone("upper_arm", "Left" if side == "Right" else "Right")
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
         "grip3": GRIP[:3, :3], "grip_t": GRIP[:3, 3] * scale, "blade": blade * scale,
         "targets": dict(TARGETS, **P.get("targets", {})), "weights": dict(WEIGHTS, **P.get("weights", {})), "grid": dict(GRID, **P.get("grid", {}))}
    hinge, bent = hinge_axis(I["Bu"], I["s0"], I["E"], I["W"])
    if hinge is None: raise SystemExit("%s: the %s arm never bends %d deg in %s: no elbow hinge to read" % (A.glb, side.lower(), BENT, R["action"]))
    C["hinge"] = np.stack([hinge, Y, np.cross(hinge, Y)], -1)
    C["shoulder_max"] = SHOULDER_MAX if turn_ok else 0.0   # an upper arm hanging on the chest: nothing to turn toward a far grip
    clip = dict({k: I[k] for k in ("c0", "s0", "Bs", "head", "other")}, G3=I["Bh"] @ C["grip3"], Gt=I["W"] + I["Bh"] @ C["grip_t"])
    try:   # path_edits name frames of the action; plan() counts from its first frame
        O = plan(clip, C, loop, [dict(e, frames={int(k) - f0: v for k, v in e["frames"].items()}) for e in P.get("path_edits", [])])
    except ValueError as e:
        raise SystemExit("%s: recipe %s: %s" % (A.motion, NAME, e))
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

    # what came out, read back from the keyed clip
    N_ = read(); before = measure(C, I["Bs"], I["Bu"], I["Bf"], I["Bh"], I["s0"], I["E"], I["W"], I["head"])
    after = measure(C, N_["Bs"], N_["Bu"], N_["Bf"], N_["Bh"], N_["s0"], N_["E"], N_["W"], N_["head"])
    over = over_targets(after, C["targets"]); G3n = N_["Bh"] @ C["grip3"]; Gtn = N_["W"] + N_["Bh"] @ C["grip_t"]
    off = np.linalg.norm(Gtn - O["Gt"], axis=1) * 100
    bl = np.degrees(np.arccos(np.clip(np.sum(G3n[:, :, 2] * O["G3"][:, :, 2], -1), -1, 1)))
    vals = lambda m, i: dict({k: round(float(m[k][i]), 1) for k in KEYS + ("elbow_above_cm", "swivel")}, hand_high=bool(m["hand_high"][i]))  # noqa: E731
    rows = [{"frame": f, "before": vals(before, i), "after": vals(after, i), "over": over[i], "grip_off_cm": round(float(off[i]), 2),
             "blade_off_deg": round(float(bl[i]), 2), "short_cm": round(float(O["short"][i]) * 100, 1),
             "weapon_roll": round(float(O["roll"][i]), 1), "shoulder_turn": float(O["turn"][i]), "cutting": bool(O["cut"][i]),
             "path_moved_cm": round(float(np.linalg.norm(O["Gt"][i] - clip["Gt"][i])) * 100, 1)} for i, f in enumerate(frames)]
    for r in rows:
        print("ARM %3d | twist %4.0f -> %4.0f | forearm roll %4.0f -> %4.0f | wrist twist %4.0f -> %4.0f, bend %4.0f -> %4.0f | elbow %+4.0f -> %+4.0f cm%s" % (
            r["frame"], *(r[w][k] for k in KEYS for w in ("before", "after")), r["before"]["elbow_above_cm"], r["after"]["elbow_above_cm"],
            " | over: " + ", ".join(r["over"]) if r["over"] else ""))
    rep = dict({"recipe": NAME, "action": R["action"], "hand": side[0], "sets_hand": side[0], "bones": list(names)}, **summary(rows))
    rep["targets"] = C["targets"]
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
