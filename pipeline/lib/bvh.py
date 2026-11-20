"""Kimodo's BVH (SOMA skeleton, cm, Y up) -> joint positions per frame, and how much the hands moved in each phase of the
motion file. No Blender: character.py ranks samples with it (README, "Choosing a sample")."""
import numpy as np


def _rot(axis, deg):
    a = np.radians(deg); c, s = np.cos(a), np.sin(a)
    R = np.zeros(a.shape + (3, 3)); i = "XYZ".index(axis); j, k = (i + 1) % 3, (i + 2) % 3   # cyclic: Ry = [[c,0,s],..]
    R[..., i, i] = 1; R[..., j, j] = c; R[..., k, k] = c; R[..., j, k] = -s; R[..., k, j] = s
    return R


def joints(path):
    """-> (positions (frames, joints, 3) in metres with Z up, joint names, seconds per frame)."""
    names, parent, offset, chans = [], [], [], []
    stack, end = [], False
    lines = iter(open(path, encoding="utf-8").read().splitlines())
    for line in lines:
        w = line.split()
        if not w: continue
        if w[0] in ("ROOT", "JOINT"):
            names.append(w[1]); parent.append(stack[-1] if stack else -1); offset.append(None); chans.append([])
        elif w[0] == "End": end = True
        elif w[0] == "{": stack.append(-2 if end else len(names) - 1)
        elif w[0] == "}":
            if stack.pop() == -2: end = False
        elif w[0] == "OFFSET" and not end: offset[-1] = [float(x) for x in w[1:4]]
        elif w[0] == "CHANNELS": chans[-1] = w[2:]
        elif w[0] == "MOTION": break
    n_frames = int(next(lines).split(":")[1]); ft = float(next(lines).split(":")[1])
    M = np.array([[float(x) for x in next(lines).split()] for _ in range(n_frames)])
    P = np.zeros((n_frames, len(names), 3)); R = np.zeros((n_frames, len(names), 3, 3)); c = 0
    for j in range(len(names)):
        loc = np.tile(np.array(offset[j], float), (n_frames, 1)); rot = np.tile(np.eye(3), (n_frames, 1, 1))
        for ch in chans[j]:
            v = M[:, c]; c += 1
            if ch.endswith("position"): loc[:, "XYZ".index(ch[0])] = v   # replaces OFFSET (Kimodo's Hips: 100 + 100 cm otherwise)
            else: rot = rot @ _rot(ch[0], v)
        p = parent[j]
        if p < 0: P[:, j], R[:, j] = loc, rot
        else: P[:, j] = P[:, p] + np.einsum("fij,fj->fi", R[:, p], loc); R[:, j] = R[:, p] @ rot
    return P[..., [0, 2, 1]] * np.array([0.01, -0.01, 0.01]), names, ft


def phase_times(motion):
    t = [0.0]
    for ph in motion["phases"]: t.append(t[-1] + float(ph["duration"]))
    return t


def activity(J, names, ft, motion):
    """Hands against the hips (metres on SOMA's ~1.75 m human): `phase_moves` = per phase, the larger of the two hands'
    extent (bounding-box diagonal) inside that phase; `range` = each hand's extent over the clip; `path` = both hands'
    path length per second."""
    hips = names.index("Hips")
    H = {s: J[:, names.index(s + "Hand")] - J[:, hips] for s in ("Left", "Right")}
    ext = lambda X: float(np.linalg.norm(X.max(0) - X.min(0))) if len(X) else 0.0
    t = phase_times(motion); n = len(J); moves = []
    for a, b in zip(t, t[1:]):
        i, k = min(int(round(a / ft)), n - 1), min(int(round(b / ft)), n - 1) + 1
        moves.append(round(max(ext(X[i:k]) for X in H.values()), 3))
    path = sum(float(np.linalg.norm(np.diff(X, axis=0), axis=1).sum()) for X in H.values()) / 2 / max(n * ft, 1e-6)
    return {"phase_moves": moves, "range": {s[0]: round(ext(X), 3) for s, X in H.items()}, "path": round(path, 3)}
