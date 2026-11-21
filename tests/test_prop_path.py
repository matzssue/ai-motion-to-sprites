"""prop_path.py: the aim's frames come from the motion file, an approved key pose's prop follows the body part it was
set against, and offsets are averaged only between frames that mean the same by them.
python -m pytest tests  (or: python tests/test_prop_path.py)"""
import json, math, os, sys

import numpy as np

H = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(H, "..", "pipeline", "lib"))
from prop_path import aim_window, aim_weight, nearest, carry, smooth_runs, best_path

SHOT = [{"duration": d, "text": "x"} for d in (1.0, 1.2, 0.8, 1.2)]   # hold, lift and aim, fire, back down


def test_shot_window():
    win = aim_window(SHOT, {"_": "note", "hold": 0, "aim": 44}, 24, fire_s=2.25)
    assert win[1] == 44 and abs(win[0] - 24) < 1e-9 and abs(win[2] - 72) < 1e-9 and abs(win[3] - 86.4) < 1e-9
    w = [aim_weight(f, win) for f in range(101)]
    assert w[0] == w[24] == 0 and w[44] == 1 and all(v == 1 for v in w[44:73]) and w[87] == 0 and w[100] == 0
    assert all(a <= b for a, b in zip(w[:45], w[1:45])) and all(a >= b for a, b in zip(w[72:], w[73:]))
    assert abs(w[34] - 0.5) < 1e-9   # half-way up the lift: from here on the stock is in the armpit pocket
    # the frames past half an aim are one run that holds the aim pose and the shot
    on = [f for f in range(101) if w[f] >= 0.5]
    assert on == list(range(on[0], on[-1] + 1)) and on[0] <= 44 and 54 in on


def test_example_motion_file():
    M = json.load(open(os.path.join(H, "..", "examples", "motion.example.json"), encoding="utf-8"))
    win = aim_window(M["phases"], M["key_poses"], 24, M["recoil"]["fire_s"])
    assert aim_weight(M["key_poses"]["aim"], win) == 1 and aim_weight(M["key_poses"]["hold"], win) == 0
    assert aim_weight(M["recoil"]["fire_s"] * 24, win) == 1


def test_no_aim_pose_means_no_window():
    assert aim_window(SHOT, {"start": 0, "hit": 12}, 24) is None
    assert aim_window(SHOT, None, 24) is None and aim_window([], {"aim": 4}, 24) is None


def test_without_a_shot_the_aim_ends_with_its_phase():
    win = aim_window(SHOT, {"hold": 0, "aim": 44}, 24)
    assert abs(win[2] - 52.8) < 1e-9 and abs(win[3] - 62.4) < 1e-9


def test_aim_pose_on_a_phase_start_rises_over_the_phase_before():
    win = aim_window(SHOT, {"hold": 0, "aim": 24}, 24)
    assert win[0] == 0 and aim_weight(12, win) == 0.5


def test_aim_from_the_first_frame_and_to_the_last():
    win = aim_window(SHOT[:2], {"aim": 0}, 24, fire_s=1.5)
    assert aim_weight(0, win) == 1 and aim_weight(52, win) == 1   # no phase after the shot: aimed to the end
    win = aim_window(SHOT[:1], {"aim": 0}, 24)
    assert all(aim_weight(f, win) == 1 for f in range(25))


def rot_z(deg):
    c, s_ = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s_, 0], [s_, c, 0], [0, 0, 1.0]])


def test_carry_keeps_the_place_on_the_body_part():
    o_key, R_key = np.array([0.2, 0.0, 1.4]), rot_z(10)
    p_key = o_key + R_key @ np.array([0.05, -0.15, -0.19])   # 15 cm behind and 19 cm below a shoulder joint
    # the same pose: the same point
    assert np.allclose(carry(p_key, o_key, R_key, o_key, R_key), p_key)
    # the part moved and turned: the point is where it was in the part's own axes
    o, R = np.array([0.5, -0.3, 1.2]), rot_z(55)
    assert np.allclose(R.T @ (carry(p_key, o_key, R_key, o, R) - o), [0.05, -0.15, -0.19])
    # without the turn it only follows the origin
    assert np.allclose(carry(p_key, o_key, None, o) - o, p_key - o_key)


def test_nearest_key_frame():
    assert nearest(30, [0, 44]) == 44 and nearest(22, [0, 44]) == 0 and nearest(22, [0, 44, 100]) == 0
    assert nearest(5, []) is None and nearest(72, [44]) == 44


def test_smooth_runs_is_the_plain_average_inside_one_run():
    rng = np.random.default_rng(1); frames = list(range(20)); off = {f: list(rng.normal(size=6)) for f in frames}
    got = smooth_runs(off, frames, lambda f: False)
    for f in frames:   # the solver's average before: every frame within 3, weight 1 - distance / 4
        acc, ws = np.zeros(6), 0
        for g in range(f - 3, f + 4):
            if g in off: ww = 1 - abs(g - f) / 4; acc += np.array(off[g]) * ww; ws += ww
        assert got[f] == list(acc / ws)   # bit for bit: clips without an armpit rest must not change


def test_smooth_runs_does_not_cross_a_change_of_state():
    frames = list(range(12)); pinned = lambda f: 4 <= f <= 8
    off = {f: [100.0, 0.0] if pinned(f) else [0.0, 7.0] for f in frames}   # two kinds of offset, far apart
    got = smooth_runs(off, frames, pinned)
    assert all(got[f] == off[f] for f in frames)   # nothing leaks from one kind into the other
    off[6] = [130.0, 0.0]; got = smooth_runs(off, frames, pinned)
    assert got[3] == [0.0, 7.0] and got[9] == [0.0, 7.0]   # outside the run: untouched
    assert 100 < got[5][0] < 130 and 100 < got[6][0] < 130 and got[4][0] > 100   # inside: smoothed
    # a run of one frame keeps its offset
    assert smooth_runs({0: [1.0], 1: [9.0], 2: [1.0]}, [0, 1, 2], lambda f: f == 1)[1] == [9.0]


def test_smooth_runs_over_the_loop_seam():
    rng = np.random.default_rng(2); frames = list(range(10, 31)); off = {f: list(rng.normal(size=4)) for f in frames}
    off[30] = list(off[10])   # the clip ends in its first frame
    got = smooth_runs(off, frames, lambda f: 0, loop=True)
    assert np.allclose(got[10], got[30])   # the same neighbours on both sides of the seam
    plain = smooth_runs(off, frames, lambda f: 0)
    assert not np.allclose(plain[10], plain[30]) and got[20] == plain[20]   # away from the seam nothing changes


def test_best_path_is_the_cheapest_chain():
    rng = np.random.default_rng(5); n, k = 9, 4; U = [rng.uniform(0, 10, k) for _ in range(n)]
    S = np.arange(k, dtype=float); trans = 0.7 * (S[:, None] - S[None, :]) ** 2
    cost = lambda p: sum(U[i][s] for i, s in enumerate(p)) + sum(trans[a, b] for a, b in zip(p, p[1:]))
    import itertools
    every = list(itertools.product(range(k), repeat=n))
    assert cost(best_path(U, trans)) == min(cost(p) for p in every)
    looped = best_path(U, trans, loop=True)
    assert looped[0] == looped[-1] and abs(cost(looped) - min(cost(p) for p in every if p[0] == p[-1])) < 1e-9


def test_best_path_keeps_a_frame_with_one_allowed_state():
    U = [np.array([0.0, 5.0, 5.0]), np.array([1e9, 1e9, 2.0]), np.array([0.0, 5.0, 5.0])]   # the middle frame: state 2 only
    trans = np.zeros((3, 3))
    assert best_path(U, trans) == [0, 2, 0] and best_path(U, trans, loop=True) == [0, 2, 0]


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("OK", name)
