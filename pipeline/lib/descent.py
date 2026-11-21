"""Parts of the prop pose search (prop_in_hands.py) that need no Blender: the coordinate descent with a cost to beat,
and faces renumbered onto the vertices they use. Tests: tests/test_descent.py."""
import numpy as np


def descend(cost, Cb, steps, rounds=3):
    """Coordinate descent from x = 0, both directions, over steps[axis] (largest first): -> (x, cost).
    cost(x, Cb, bound=None) is the full cost without `bound`; with it, a pose that costs at least `bound` may come back
    as any value >= bound, unfinished. Only a strictly lower cost is ever taken, so the answer is the one a search that
    measures every pose to the end gives."""
    x = [0.0] * len(steps); best = cost(x, Cb)
    if best == 0: return x, best
    for _ in range(rounds):
        better = False
        for axis, sizes in enumerate(steps):
            for st in sizes:
                for sg in (1, -1):
                    y = list(x); y[axis] += sg * st; c = cost(y, Cb, bound=best)
                    if c < best: best, x, better = c, y, True
        if not better or best == 0: break
    return x, best


def faces_on(T):
    """(vertices the faces T use, T numbered on those vertices): V[I][T2] is V[T], so a tree built from V[I] and T2 has
    the same triangles in the same order as one built from all of V and T."""
    if not len(T): return np.zeros(0, int), []
    T = np.asarray(T); I = np.unique(T)
    return I, np.searchsorted(I, T).tolist()
