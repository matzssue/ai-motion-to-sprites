"""Feet against the ground for motion_audit.py: the character off the ground, a planted foot sliding, one foot hanging.
Plain numpy on the foot skin of every audit sample (no Blender; tests run it on synthetic feet). The ground is the clip's
own lowest foot point: combine_actions.py puts every action on one ground afterwards, so an offset of the whole clip is
not a defect, only a change of foot height inside it. Limits and their measurement: AUDIT.md "Feet"."""
import numpy as np

CONTACT = 0.03      # m for a 1.8 m character: foot skin this close to the clip's ground stands on it (4 cm let a walk's toe
                    # roll in and read as a 46 cm slide)
SLIDE_FRAMES = 2.0  # a planted foot's net travel is measured over this many frames
MIN_CONTACT = 3     # vertices of one foot on the ground in two samples in a row, or that step is not a contact


def _contact_steps(F, g, c):
    """Per sample: median ground-plane travel (x, y) since the previous sample of the foot skin on the ground in both,
    or None. The median of the touching skin, not its lowest point: the lowest vertex jumps between heel and toe."""
    out = [None]
    for i in range(1, len(F)):
        m = ((F[i - 1, :, 2] - g) < c) & ((F[i, :, 2] - g) < c)
        out.append(np.median(F[i, m, :2] - F[i - 1, m, :2], axis=0) if m.sum() >= MIN_CONTACT else None)
    return out


def rows(feet, scale, step):
    """feet {"L": [samples, vertices, 3], "R": ...} foot skin in world space (z up) at every audit sample, `scale` =
    height / 1.8, `step` = frames per sample. Returns one dict per sample: {"values": {metric: v}, "where": {metric:
    [x, y, z]}, "side": {metric: "L"/"R"}} for feet_above_ground, foot_slide and foot_hanging."""
    sides = [s for s in ("L", "R") if s in feet and feet[s].shape[1]]
    n = len(feet[sides[0]]) if sides else 0
    out = [{"values": {}, "where": {}, "side": {}} for _ in range(n)]
    if not n: return out
    F = {s: np.asarray(feet[s], float) for s in sides}
    low = {s: F[s][..., 2].min(1) for s in sides}
    g = min(float(v.min()) for v in low.values())
    c = CONTACT * scale
    # in-place locomotion (a library walk) moves every planted foot back at the walking speed: that "treadmill" is the
    # median travel of all contact steps; an action standing in place has it ~0 (m1 attacks 0.0001-0.0005 m per step)
    st = {s: _contact_steps(F[s], g, c) for s in sides}
    every = [v for s in sides for v in st[s] if v is not None]
    tread = np.median(every, axis=0) if every else np.zeros(2)
    w = max(1, int(round(SLIDE_FRAMES / step)))
    for i in range(n):
        o = out[i]
        s0 = min(sides, key=lambda s: low[s][i]); k = int(F[s0][i, :, 2].argmin())
        o["values"]["feet_above_ground"] = round(float(low[s0][i] - g), 4)
        o["where"]["feet_above_ground"] = [float(x) for x in F[s0][i, k]]
        best = (0.0, None)
        for s in sides:
            win = st[s][max(0, i - w + 1):i + 1]
            if len(win) == w and all(v is not None for v in win):
                v = float(np.linalg.norm(np.sum(win, axis=0) - w * tread))
                if v > best[0]: best = (v, s)
        o["values"]["foot_slide"] = round(best[0], 4)
        if best[1]:
            m = (F[best[1]][i, :, 2] - g) < c
            o["where"]["foot_slide"] = [float(x) for x in F[best[1]][i, m].mean(0)]; o["side"]["foot_slide"] = best[1]
        o["values"]["foot_hanging"] = 0.0
        if len(sides) == 2:
            up = max(sides, key=lambda s: low[s][i])
            if low[s0][i] - g < c and low[up][i] - g > c:
                o["values"]["foot_hanging"] = round(float(low[up][i] - g), 4); o["side"]["foot_hanging"] = up
                o["where"]["foot_hanging"] = [float(x) for x in F[up][i, int(F[up][i, :, 2].argmin())]]
    return out
