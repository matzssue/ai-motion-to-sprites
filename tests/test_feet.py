"""Feet against the ground (pipeline/lib/feet.py) on synthetic feet: a sole of 12 vertices plus an ankle point."""
import os, sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pipeline", "lib"))
import feet  # noqa: E402

STEP = 0.25   # frames per audit sample


def foot(x, y, z):
    """Sole 25 x 10 cm with its lowest point at z, ankle 8 cm above it."""
    sole = [(x + dx, y + dy, z) for dx in np.linspace(-0.12, 0.12, 4) for dy in (-0.05, 0.0, 0.05)]
    return np.array(sole + [(x, y, z + 0.08)])


def clip(left, right):
    """left/right: [(x, y, z)] per sample -> {"L", "R"} arrays [samples, vertices, 3]."""
    return {"L": np.array([foot(*p) for p in left]), "R": np.array([foot(*p) for p in right])}


def column(rows, k):
    return np.array([r["values"][k] for r in rows])


def test_standing_still_is_clean():
    n = 40
    r = feet.rows(clip([(0.1, 0, 0)] * n, [(-0.1, 0, 0)] * n), 1.0, STEP)
    assert len(r) == n
    for k in ("feet_above_ground", "foot_slide", "foot_hanging"):
        assert column(r, k).max() == 0


def test_whole_clip_offset_is_not_floating():
    # combine_actions.py grounds every action afterwards: only height changes inside the clip count
    n = 20
    r = feet.rows(clip([(0.1, 0, 0.5)] * n, [(-0.1, 0, 0.5)] * n), 1.0, STEP)
    assert column(r, "feet_above_ground").max() == 0


def test_crouch_at_standing_hip_height_floats():
    # key-pose crouch with the hips left at standing height: both feet 40 cm up, then down on the ground
    up = [(0.1, 0, 0.4)] * 10 + [(0.1, 0, 0.0)] * 10
    r = feet.rows(clip(up, [(-0.1, 0, z) for _, _, z in up]), 1.0, STEP)
    v = column(r, "feet_above_ground")
    assert abs(v.max() - 0.4) < 1e-6 and v[0] == v.max() and v[-1] == 0
    assert column(r, "foot_slide").max() == 0      # nothing on the ground while it floats


def test_planted_foot_sliding_is_measured_over_two_frames():
    n = 30
    right = [(-0.1 + (0.05 * (i - 10) if i >= 10 else 0.0), 0, 0) for i in range(n)]   # skates 5 cm per sample from 10
    r = feet.rows(clip([(0.1, 0, 0)] * n, right), 1.0, STEP)
    v = column(r, "foot_slide")
    w = int(feet.SLIDE_FRAMES / STEP)
    assert abs(v.max() - 0.05 * w) < 1e-6           # net travel over the window
    assert r[int(v.argmax())]["side"]["foot_slide"] == "R"
    assert v[:11].max() == 0


def test_walk_in_place_treadmill_is_not_a_slide():
    # library walk in place: the planted foot moves back at a constant speed, the swing foot comes forward in the air
    speed, n = 0.01, 64
    def leg(phase):
        out = []
        for i in range(n):
            u = (i + phase) % 32
            out.append((0.08 - speed * u, 0, 0) if u < 16 else (-0.08 + speed * (u - 16), 0, 0.1))
        return out
    r = feet.rows(clip(leg(0), leg(16)), 1.0, STEP)
    assert column(r, "foot_slide").max() < 1e-6
    assert column(r, "feet_above_ground").max() == 0


def test_one_foot_hanging_is_reported_with_its_side():
    n = 12
    r = feet.rows(clip([(0.1, 0, 0)] * n, [(-0.1, 0, 0.3)] * n), 1.0, STEP)
    v = column(r, "foot_hanging")
    assert abs(v.max() - 0.3) < 1e-6 and r[0]["side"]["foot_hanging"] == "R"


def test_contact_and_limits_scale_with_height():
    # a foot 4 cm up is off the ground for a 1.8 m character (3 cm contact) but on it for a 2.7 m one (4.5 cm)
    n = 12
    small = feet.rows(clip([(0.1, 0, 0)] * n, [(-0.1, 0, 0.04)] * n), 1.0, STEP)
    big = feet.rows(clip([(0.1, 0, 0)] * n, [(-0.1, 0, 0.04)] * n), 1.5, STEP)
    assert column(small, "foot_hanging").max() > 0 and column(big, "foot_hanging").max() == 0
