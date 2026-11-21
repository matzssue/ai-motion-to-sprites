"""Rules of the two steps that take the upper body away from the motion model (plain numpy; pose_upper_body.py and
head_forward.py apply them in Blender, tests run them): a rotation track through key poses, and where the head should look.
Quaternions are (w, x, y, z)."""
import numpy as np

UP = np.array([0.0, 0.0, 1.0])


def hermite(x, y, t, scale=None):
    """Cubic Hermite through the points (x[i], y[i]) at the times `t`; y may hold several columns. The tangent at an inner
    point is Catmull-Rom's (y[i+1] - y[i-1]) / (x[i+1] - x[i-1]) times `scale.get(x[i], 1)`; both ends are flat. Unlike a
    monotone cubic it does not brake at every key: a strike passes through its key at speed."""
    x = np.asarray(x, float); y = np.asarray(y, float); y2 = y[:, None] if y.ndim == 1 else y; h = np.diff(x); m = np.zeros_like(y2)
    for i in range(1, len(x) - 1):
        m[i] = (y2[i + 1] - y2[i - 1]) / (x[i + 1] - x[i - 1]) * (scale or {}).get(int(x[i]), 1.0)
    out = []
    for tt in np.atleast_1d(np.asarray(t, float)):
        i = min(max(int(np.searchsorted(x, tt)) - 1, 0), len(h) - 1); s = (tt - x[i]) / h[i]
        out.append((2 * s**3 - 3 * s**2 + 1) * y2[i] + (s**3 - 2 * s**2 + s) * h[i] * m[i]
                   + (-2 * s**3 + 3 * s**2) * y2[i + 1] + (s**3 - s**2) * h[i] * m[i + 1])
    out = np.array(out); return out[:, 0] if y.ndim == 1 else out


def track(keys, quats, end, times, scale=None, loop=True):
    """One bone's rotation at `times` from its key poses: `quats` [k, 4] on the frames `keys` (sorted, the first at the
    clip's start), then the first pose again at `end` (a loop) or the last pose held to it. Neighbouring quaternions are
    put in one hemisphere, each component runs through `hermite`, the result is normalised."""
    q = [np.asarray(v, float) for v in quats]; x = [float(k) for k in keys]
    if loop and end > x[-1]: q.append(q[0].copy()); x.append(float(end))
    for i in range(1, len(q)):
        if q[i] @ q[i - 1] < 0: q[i] = -q[i]
    out = hermite(x, np.array(q), np.minimum(np.asarray(times, float), x[-1]), scale)   # past the last key: held
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def key_times(first, last):
    """Whole frames from `first` to `last`, and `last` itself when the clip ends between two frames (a retargeted clip
    keeps the model's 30 fps keys in a 24 fps scene: 55.2)."""
    t = list(range(int(np.ceil(first - 1e-6)), int(np.floor(last + 1e-6)) + 1))
    return t + [float(last)] if last - t[-1] > 1e-4 else t


# --- head direction: yaw + toward the character's left, pitch + down, against the way the rest pose faces ---
def direction(yaw, pitch, facing):
    """(forward, up) unit vectors of a head turned `yaw` and tilted `pitch` deg off `facing`, without roll."""
    f0 = np.asarray(facing, float); left = np.cross(UP, f0); y, p = np.radians(yaw), np.radians(pitch)
    f = f0 * np.cos(y) * np.cos(p) + left * np.sin(y) * np.cos(p) - UP * np.sin(p)
    u = UP - f * (f @ UP); return f, u / np.linalg.norm(u)


def head_target(mode, yaw, pitch, yaw0, pitch0, chest_yaw, pitch_deg=3.0, keep=1.0, chest_max=70.0):
    """Where the head should look on one frame -> (yaw, pitch, capped). `lock`: straight ahead with `pitch_deg` down.
    `keep`: the clip's own head motion since its first frame (yaw0, pitch0), times `keep`, on top of that; the first frame
    faces forward either way, so clips join. The head never turns more than `chest_max` from the chest: it lags behind."""
    ty, tp = (0.0, pitch_deg) if mode == "lock" else (keep * (yaw - yaw0), pitch_deg + keep * (pitch - pitch0))
    capped = abs(ty - chest_yaw) > chest_max
    if capped: ty = chest_yaw + float(np.copysign(chest_max, ty - chest_yaw))
    return ty, tp, bool(capped)
