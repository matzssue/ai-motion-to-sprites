"""weight_reach.gate (no Blender): a cloth panel hanging in front of a leg, whose hem bone heat gave to the toe.
python -m pytest tests  (or: python tests/test_weight_reach.py)"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
import weight_reach as WR

BONES = {"hips": ((0.0, 0.0, 1.0), (0.0, 0.0, 1.2)), "thigh": ((0.1, 0.0, 0.95), (0.1, 0.0, 0.5)),
         "shin": ((0.1, 0.0, 0.5), (0.1, 0.0, 0.08)), "foot": ((0.1, 0.0, 0.08), (0.1, -0.12, 0.02)),
         "toe": ((0.1, -0.12, 0.02), (0.1, -0.2, 0.02))}
NAMES = list(BONES); B = {n: i for i, n in enumerate(NAMES)}
HEADS = np.array([BONES[n][0] for n in NAMES]); TAILS = np.array([BONES[n][1] for n in NAMES])


def tube(a, b, r, n_along, n_round=8):
    a, b = np.array(a), np.array(b); d = (b - a) / np.linalg.norm(b - a)
    u = np.cross(d, (1, 0, 0) if abs(d[0]) < 0.9 else (0, 1, 0)); u /= np.linalg.norm(u); w = np.cross(d, u)
    return np.array([a + t * (b - a) + r * (np.cos(p) * u + np.sin(p) * w)
                     for t in np.linspace(0.05, 0.95, n_along) for p in np.linspace(0, 2 * np.pi, n_round, endpoint=False)])


def scene():
    """Leg skin (rings round each leg bone, weighted to it) + a 10 x 12 cloth grid 15 cm in front of the leg from the hips
    down to 0.45 m: hips on top, thigh blended in lower down, the bottom two rows on the toe 45 cm below them."""
    skin = [(tube(*BONES[n], r, k), n) for n, r, k in (("thigh", 0.07, 8), ("shin", 0.05, 8), ("foot", 0.04, 4), ("toe", 0.025, 4))]
    co = [p for P, _ in skin for p in P]; W = []
    for P, n in skin:
        for _ in P:
            w = np.zeros(len(NAMES)); w[B[n]] = 1.0; W.append(w)
    n_leg = len(co)
    xs, zs = np.linspace(0.0, 0.2, 10), np.linspace(0.95, 0.45, 12)
    grid = np.arange(len(xs) * len(zs)).reshape(len(zs), len(xs)) + n_leg
    for i, z in enumerate(zs):
        for x in xs:
            co.append((x, -0.15, z)); w = np.zeros(len(NAMES))
            if i >= len(zs) - 2: w[B["toe"]] = 1.0
            else: k = i / (len(zs) - 1); w[B["hips"]] = 1.0 - 0.6 * k; w[B["thigh"]] = 0.6 * k
            W.append(w)
    edges = [(grid[i, j], grid[i, j + 1]) for i in range(len(zs)) for j in range(len(xs) - 1)]
    edges += [(grid[i, j], grid[i + 1, j]) for i in range(len(zs) - 1) for j in range(len(xs))]
    return np.array(co), np.array(edges), np.array(W), n_leg, grid


def test_hem_leaves_the_toe_and_takes_the_cloth_above():
    co, edges, W, n_leg, grid = scene()
    gated = [B[n] for n in ("thigh", "shin", "foot", "toe")]
    W2, rep = WR.gate(co, edges, W, HEADS, TAILS, gated)
    hem = grid[-2:].ravel()
    assert np.all(W2[hem, B["toe"]] == 0.0)                              # nothing of the toe 45 cm away
    assert np.allclose(W2[hem].sum(1), 1.0)
    above = W2[grid[-3]]                                                  # as the row it hangs from
    assert np.allclose(W2[grid[-2]], above, atol=1e-9) and np.allclose(W2[grid[-1]], above, atol=1e-9)
    assert np.array_equal(W2[:n_leg], W[:n_leg]) and np.array_equal(W2[grid[:-2].ravel()], W[grid[:-2].ravel()])
    assert set(rep) == {B["toe"]} and rep[B["toe"]][0] == len(hem)


def test_weight_within_reach_is_kept():
    """Skin close to a bone (bone heat's normal blend at a joint) is not touched, nor the trunk bones that cloth hangs from."""
    co, edges, W, n_leg, grid = scene()
    W[grid[-2:].ravel()] = 0.0; W[grid[-2:].ravel(), B["hips"]] = 1.0      # no toe on the hem this time
    near = np.argmin(np.linalg.norm(co[:n_leg] - TAILS[B["shin"]], axis=1))
    W[near] = 0.0; W[near, B["shin"]] = 0.5; W[near, B["foot"]] = 0.5      # ankle skin blended shin/foot
    W2, rep = WR.gate(co, edges, W, HEADS, TAILS, [B[n] for n in ("thigh", "shin", "foot", "toe")])
    assert np.array_equal(W2, W) and rep == {}


def test_shell_with_nothing_in_reach_keeps_its_rest():
    """A loose piece whose every vertex lost weight has no neighbour to take from: what is left, renormalised; a vertex left
    with nothing keeps its weights (a weightless vertex would stay behind in every pose)."""
    co, edges, W, n_leg, grid = scene()
    piece = grid[-2:].ravel()
    W[piece] = 0.0; W[piece[:5], B["toe"]] = 1.0; W[piece[5:], B["toe"]] = 0.5; W[piece[5:], B["hips"]] = 0.5
    keep = np.array([e for e in edges if not (np.isin(e, piece).sum() == 1)])   # cut the hem off the panel
    W2, _ = WR.gate(co, keep, W, HEADS, TAILS, [B["toe"]])
    assert np.allclose(W2[piece[5:], B["hips"]], 1.0) and np.array_equal(W2[piece[:5]], W[piece[:5]])


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"): f(); print("ok", k)
