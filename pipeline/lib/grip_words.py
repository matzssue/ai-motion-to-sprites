"""Grip of prop_in_hands.py in words <-> vectors in the prop frame (X forward along the stock, Y to the character's LEFT,
Z up). Blender uses mathutils.Vector; outside Blender (tests) a numpy stand-in with the same few operations."""
import math

try:
    from mathutils import Vector
except ImportError:
    import numpy as np

    class Vector:
        """numpy stand-in for mathutils.Vector: only what this module uses."""
        def __init__(self, v): self.v = np.array([float(x) for x in v])
        def normalized(self): n = np.linalg.norm(self.v); return Vector(self.v / n if n else self.v)
        def dot(self, o): return float(self.v @ o.v)
        def __mul__(self, k): return Vector(self.v * k)
        __rmul__ = __mul__
        def __add__(self, o): return Vector(self.v + o.v)
        def __sub__(self, o): return Vector(self.v - o.v)
        def __iter__(self): return iter(self.v.tolist())
        def __len__(self): return len(self.v)
        def __getitem__(self, i): return float(self.v[i])
        @property
        def length(self): return float(np.linalg.norm(self.v))


AXES = {"forward": (1, 0, 0), "back": (-1, 0, 0), "left": (0, 1, 0), "right": (0, -1, 0), "up": (0, 0, 1), "down": (0, 0, -1)}
# side of the prop the hand is on -> where its palm faces
PALM_SIDE = {"from below": (0, 0, 1), "from above": (0, 0, -1), "from the right": (0, 1, 0), "from the left": (0, -1, 0),
             "from behind": (1, 0, 0), "from the front": (-1, 0, 0)}


def nearest(tab, v):
    v = Vector(v).normalized(); return max(tab, key=lambda k: v.dot(Vector(tab[k])))


def grip_from_words(g):
    """`palm`: "from below", `fingers`: "left", `fingers_tilt`: ["forward", 18] -> palm_normal, direction (when given in words)."""
    if "palm" in g: g["palm_normal"] = list(PALM_SIDE[g["palm"]])
    if "fingers" in g:
        d = Vector(AXES[g["fingers"]]); toward, deg = g.get("fingers_tilt", ("forward", 0))
        g["direction"] = list(d * math.cos(math.radians(deg)) + Vector(AXES[toward]) * math.sin(math.radians(deg)))
    return g


def grip_in_words(g, butt):
    d = Vector(g["direction"]).normalized(); a = nearest(AXES, d); rest = d - Vector(AXES[a]) * d.dot(Vector(AXES[a]))
    tilt = math.degrees(math.asin(min(1.0, rest.length)))
    return "palm %s, fingers %s%s, %.0f cm in front of the butt" % (
        nearest(PALM_SIDE, g["palm_normal"]), a, " and %.0f deg %s" % (tilt, nearest(AXES, rest)) if tilt > 3 else "", 100 * (g["x"] - butt))
