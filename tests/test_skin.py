"""skin.py on a synthetic arm (no Blender): a tube along the upper arm and forearm, twisted or scattered.
python -m pytest tests  (or: python tests/test_skin.py)"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
import skin

HEADS = {"LeftShoulder": np.array([0.10, 0, 1.45]), "LeftArm": np.array([0.18, 0, 1.45]),
         "LeftForeArm": np.array([0.46, 0, 1.45]), "LeftHand": np.array([0.72, 0, 1.45])}


def tube(a, b, bone, rings=24, per_ring=24, r=0.04):
    t = np.repeat(np.linspace(-0.2, 1.0, rings), per_ring); ang = np.tile(np.linspace(0, 2 * np.pi, per_ring, endpoint=False), rings)
    d = (b - a) / np.linalg.norm(b - a); u = np.cross(d, [0, 0, 1.0]); u /= np.linalg.norm(u); v = np.cross(d, u)
    pts = a + np.outer(t, b - a) + r * (np.outer(np.cos(ang), u) + np.outer(np.sin(ang), v))
    return pts, t, np.full(len(pts), bone, dtype=object)


def arm_mesh():
    p1, t1, d1 = tube(HEADS["LeftArm"], HEADS["LeftForeArm"], "LeftArm")
    p2, t2, d2 = tube(HEADS["LeftForeArm"], HEADS["LeftHand"], "LeftForeArm")
    return np.vstack([p1, p2]), np.concatenate([t1, t2]), np.concatenate([d1, d2])


def rotate_about(p, a, d, ang):
    d = d / np.linalg.norm(d); q = p - a; c, s = np.cos(ang), np.sin(ang)
    return a + q * c[:, None] + np.cross(d, q) * s[:, None] + np.outer(q @ d, d) * (1 - c)[:, None]


def measure(posed, rest, dom):
    sel = skin.select(dom, rest, HEADS, "Left")
    seg = sel["LeftForeArm"]
    return skin.twist(rest, posed, seg, HEADS["LeftForeArm"], HEADS["LeftHand"], HEADS["LeftForeArm"], HEADS["LeftHand"], np.eye(3))


def test_rest_is_clean():
    rest, t, dom = arm_mesh()
    tw, spread = measure(rest, rest, dom)
    assert abs(tw) < 10 and spread < 0.05


def test_candy_wrapper_twist_fails():
    rest, t, dom = arm_mesh()
    fore = dom == "LeftForeArm"; posed = rest.copy()
    d = HEADS["LeftHand"] - HEADS["LeftForeArm"]
    posed[fore] = rotate_about(rest[fore], HEADS["LeftForeArm"], d, np.radians(250) * np.clip(t[fore], 0, 1))
    tw, spread = measure(posed, rest, dom)
    assert abs(tw) > skin.TWIST_MAX and abs(abs(tw) - 250) <= 20


def test_mild_twist_passes():
    rest, t, dom = arm_mesh()
    fore = dom == "LeftForeArm"; posed = rest.copy()
    d = HEADS["LeftHand"] - HEADS["LeftForeArm"]
    posed[fore] = rotate_about(rest[fore], HEADS["LeftForeArm"], d, np.radians(40) * np.clip(t[fore], 0, 1))
    tw, spread = measure(posed, rest, dom)
    assert abs(tw) < skin.TWIST_MAX and spread < skin.SPREAD_MAX


def test_scattered_skin_spreads():
    rest, t, dom = arm_mesh()
    fore = dom == "LeftForeArm"; posed = rest.copy()
    d = HEADS["LeftHand"] - HEADS["LeftForeArm"]
    noise = np.random.default_rng(3).uniform(-np.pi, np.pi, fore.sum())
    posed[fore] = rotate_about(rest[fore], HEADS["LeftForeArm"], d, noise)
    tw, spread = measure(posed, rest, dom)
    assert spread > skin.SPREAD_MAX


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
