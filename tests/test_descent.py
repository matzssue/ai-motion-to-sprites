"""descent.py (prop pose search of prop_in_hands.py): a cost to beat changes how much is measured, never the answer.
python -m pytest tests  (or: python tests/test_descent.py)"""
import os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
from descent import descend, faces_on

STEPS = ((0.02, 0.01), (0.02, 0.01), (0.04, 0.02, 0.01), (20, 10, 5), (10, 5), (10, 5))   # the pinned search's steps


def staged(seed):
    """A cost built like the solver's: parts that are all >= 0, added in a fixed order, the later ones dearer to measure.
    -> (cost, log): cost(x, Cb, bound) stops at the first part whose running sum cannot beat `bound`; log counts the
    parts measured."""
    rng = np.random.default_rng(seed); target = rng.normal(0, (0.02, 0.02, 0.03, 12, 6, 6)); w = rng.uniform(0.5, 3, (3, 6))
    log = {"parts": 0, "cut": 0}

    def cost(x, Cb, bound=None):
        tail = 0.3 * sum(abs(v) for v in x[3:]) + 100 * (x[0] ** 2 + x[1] ** 2 + x[2] ** 2) ** 0.5
        c = 0.0
        for k in range(3):
            if bound is not None and c + tail >= bound: log["cut"] += 1; return 1e9
            log["parts"] += 1
            c += float(w[k] @ np.abs((np.array(x) - target) * (50, 50, 50, 0.2, 0.2, 0.2)) ** (k + 1))
        return c + tail
    return cost, log


def test_bound_does_not_change_the_answer():
    cut = 0
    for seed in range(40):
        cost, log = staged(seed); full, log_full = staged(seed)
        got = descend(cost, None, STEPS)
        want = descend(lambda x, Cb, bound=None: full(x, Cb), None, STEPS)
        assert got == want, seed
        assert log["parts"] <= log_full["parts"]
        cut += log["cut"]
    assert cut > 0   # the bound did cut work somewhere, or the test proves nothing


def test_zero_cost_start_is_kept():
    calls = []

    def cost(x, Cb, bound=None):
        calls.append(tuple(x)); return 0.0
    assert descend(cost, None, STEPS) == ([0.0] * 6, 0.0) and len(calls) == 1


def test_ties_keep_the_first_pose():
    # a step that only equals the best is not taken (the solver's "ties go to the first")
    assert descend(lambda x, Cb, bound=None: 5.0, None, STEPS)[0] == [0.0] * 6


def test_empty_axes_are_skipped():
    T = (0.08, 0.04, 0.02); steps = (T, T, T, (20, 10, 5), (), ())   # the hold search on a 6-value offset
    x, best = descend(lambda x, Cb, bound=None: abs(x[0] - 0.06) + abs(x[4] - 3.0), None, steps)
    assert abs(x[0] - 0.06) < 1e-12 and x[4] == 0.0 and abs(best - 3.0) < 1e-12


def test_faces_on_keeps_triangles_and_order():
    rng = np.random.default_rng(3); V = rng.normal(size=(500, 3))
    T = rng.choice(np.arange(40, 300, 3), (120, 3))   # faces that use a part of the vertices, some of them twice
    I, T2 = faces_on(T.tolist())
    assert len(I) < len(V) and I.tolist() == sorted(set(T.ravel().tolist()))
    assert np.array_equal(V[I][np.array(T2)], V[T])   # same coordinates, face by face, corner by corner


def test_faces_on_nothing():
    I, T2 = faces_on([])
    assert len(I) == 0 and T2 == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("OK", name)
