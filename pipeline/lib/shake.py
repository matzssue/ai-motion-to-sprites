"""Shake of the pelvis and knees in a clip (plain numpy; motion_audit.py measures, tests run it): each whole frame's value
minus the mean of the 5 frames centred on it. A smooth turn or step leaves almost nothing; a pelvis that snaps to a key
pose and falls back between keys does (Kimodo key poses with the root forced forward in place, knight round 7)."""
import numpy as np

WINDOW = 5


def residual(x):
    """x [frames, dims] -> [frames] distance from the centred WINDOW-frame mean; the first and last WINDOW // 2 frames 0."""
    x = np.asarray(x, float); x = x[:, None] if x.ndim == 1 else x; h = WINDOW // 2; out = np.zeros(len(x))
    if len(x) < WINDOW: return out
    k = np.ones(WINDOW) / WINDOW
    sm = np.stack([np.convolve(x[:, i], k, mode="valid") for i in range(x.shape[1])], 1)
    out[h:len(x) - h] = np.linalg.norm(x[h:len(x) - h] - sm, axis=1)
    return out


def yaw_deg(right_hip, left_hip):
    """Pelvis yaw per frame (deg, unwrapped) from the hip joints, Blender world (Z up)."""
    d = np.asarray(right_hip, float) - np.asarray(left_hip, float)
    return np.degrees(np.unwrap(np.arctan2(d[:, 1], d[:, 0])))


def rows(right_hip, left_hip, knee_l, knee_r):
    """(pelvis_shake deg, knee_shake m) per frame."""
    return residual(yaw_deg(right_hip, left_hip)), np.maximum(residual(knee_l), residual(knee_r))
