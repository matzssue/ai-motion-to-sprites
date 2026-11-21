"""Key poses' hand rotation put back after the model (pipeline/lib/keyhands.py), on synthetic rotations."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline", "lib"))
import keyhands as KH  # noqa: E402

Y = (0.0, 1.0, 0.0)


def rand_q(rng):
    q = rng.normal(size=4); return q / np.linalg.norm(q)


def test_forearm_roll_recovers_the_twist():
    """hand = forearm @ Ry(t) @ L: the twist of forearm^-1 @ target @ L^-1 about Y is t, and applying it hits the target."""
    rng = np.random.default_rng(1)
    for t in (-2.9, -1.0, 0.0, 0.7, 3.0):
        Fw, L = rand_q(rng), rand_q(rng)
        T = KH.qmul(KH.qmul(Fw, KH.axis_angle(Y, t)), L)
        got = KH.twist(KH.qmul(KH.qmul(KH.qinv(Fw), T), KH.qinv(L)), Y)
        assert abs((got - t + math.pi) % (2 * math.pi) - math.pi) < 1e-9
        assert KH.angle(KH.qmul(KH.qmul(Fw, KH.axis_angle(Y, got)), L), T) < 1e-6


def test_roll_is_the_closest_turn_about_the_axis():
    """A target off the roll's reach: the twist leaves less error than any other roll."""
    rng = np.random.default_rng(2); D = rand_q(rng); t = KH.twist(D, Y)
    best = KH.angle(KH.axis_angle(Y, t), D)
    assert all(KH.angle(KH.axis_angle(Y, math.radians(a)), D) >= best - 1e-9 for a in range(-180, 181, 3))


def test_schedule_hits_keys_and_loops_back():
    keys = {0: 0, 12: 0, 20: 0}
    s = KH.schedule(keys, 30, True, [0, 6, 12, 25, 30])
    ext = [f for f, _ in KH.extend(keys, 30, True)]
    assert [ext[i] for i, j, t in s if t == 0.0] == [0, 12, 30]       # frame 30 of a closed loop = the first key's copy
    assert s[1][2] == pytest.approx(0.5) and ext[s[3][0]] == 20 and ext[s[3][1]] == 30


def test_one_shot_holds_the_end_keys():
    s = KH.schedule({5: 0, 10: 0}, 20, False)
    ext = [f for f, _ in KH.extend({5: 0, 10: 0}, 20, False)]
    assert all(ext[i] == 5 and t == 0 for i, _, t in s[:6]) and all(ext[i] == 10 and t == 0 for i, _, t in s[10:])


def test_roll_track_takes_the_short_way_and_closes_the_loop():
    r = {0: math.radians(46), 10: math.radians(-166)}
    tr = KH.roll_track(r, 20, True, [0, 5, 10, 15, 20])
    assert math.degrees(tr[2]) == pytest.approx(194)                # +46 -> +194, not back through 0
    assert math.degrees(tr[1]) == pytest.approx(120)
    assert math.degrees(tr[4]) % 360 == pytest.approx(46)           # the loop's end is the first key (a whole turn away)
    assert abs(math.degrees(tr[4]) - math.degrees(tr[3])) < 90      # seam step stays short


def test_quat_track_fractional_times():
    a, b = KH.ID, KH.axis_angle(Y, math.radians(90))
    tr = KH.quat_track({0: a, 8: b}, 16, True, [0.0, 0.8, 4.0, 8.0, 15.2, 16.0])
    assert KH.angle(tr[0], a) < 1e-9 and KH.angle(tr[3], b) < 1e-9 and KH.angle(tr[5], a) < 1e-9
    assert KH.angle(tr[2], a) == pytest.approx(45, abs=1e-6)       # smoothstep midpoint
    assert 0 < KH.angle(tr[1], a) < 45 * 0.8 / 4                    # eased start


def test_limit_wrist_cuts_twist_and_bend_only_past_the_limits():
    q = KH.qmul(KH.axis_angle((1, 0, 0), math.radians(100)), KH.axis_angle(Y, math.radians(150)))
    c = KH.limit_wrist(q, Y, 55, 80)
    assert abs(math.degrees(KH.twist(c, Y))) == pytest.approx(55, abs=1e-6) and KH.swing_deg(c, Y) == pytest.approx(80, abs=1e-6)
    ok = KH.qmul(KH.axis_angle((0, 0, 1), math.radians(30)), KH.axis_angle(Y, math.radians(-20)))
    assert KH.angle(KH.limit_wrist(ok, Y, 55, 80), ok) < 1e-9


def test_wrist_from_pose_hits_the_target_with_the_pose_wrist():
    rng = np.random.default_rng(3)
    for _ in range(5):
        Fw, rest = rand_q(rng), rand_q(rng)
        pose = KH.qmul(KH.axis_angle((1, 0, 0), math.radians(30)), KH.axis_angle(Y, math.radians(-25)))
        T = KH.qmul(KH.qmul(KH.qmul(Fw, KH.axis_angle(Y, 1.3)), rest), pose)   # Kimodo's forearm 1.3 rad off in roll
        roll, w = KH.wrist_from_pose(Fw, T, rest, pose, Y)
        assert roll == pytest.approx(1.3) and KH.angle(w, pose) < 1e-6
        assert KH.angle(KH.qmul(KH.qmul(KH.qmul(Fw, KH.axis_angle(Y, roll)), rest), w), T) < 1e-6


def test_key_roll_far_from_its_neighbours_keeps_the_wrist_within_limits():
    """Knight round 7, left hand: the forearm roll on key 30 came out +44 deg against -59 and -6 on its neighbours, and the
    old correction kept Kimodo's own wrist (twisted ~150 deg there). The wrist now comes from the poses: within the limits
    on the keys and on every frame between them, whatever the rolls do; the hand still hits each key."""
    rng = np.random.default_rng(4); rest = rand_q(rng); keys = [22, 25, 30, 38]; n = 56
    rolls = {22: -59, 25: -30, 30: 44, 38: -6}
    poses = {f: KH.qmul(KH.axis_angle((1, 0, 0), math.radians(20 + f)), KH.axis_angle(Y, math.radians(-15 - f % 7))) for f in keys}
    Fw = {f: rand_q(rng) for f in keys}
    T = {f: KH.qmul(KH.qmul(KH.qmul(Fw[f], KH.axis_angle(Y, math.radians(rolls[f]))), rest), poses[f]) for f in keys}
    R, W = {}, {}
    for f in keys:
        R[f], w = KH.wrist_from_pose(Fw[f], T[f], rest, poses[f], Y); W[f] = KH.limit_wrist(w, Y, 55, 80)
        assert math.degrees(R[f]) == pytest.approx(rolls[f], abs=1e-6)
        assert KH.angle(KH.qmul(KH.qmul(KH.qmul(Fw[f], KH.axis_angle(Y, R[f])), rest), W[f]), T[f]) < 1e-6
    times = [i * 0.25 for i in range(n * 4)]
    for q in KH.quat_track(W, n, True, times):
        q = KH.limit_wrist(q, Y, 55, 80)
        assert abs(math.degrees(KH.twist(q, Y))) <= 55 + 1e-6 and KH.swing_deg(q, Y) <= 80 + 1e-6
    tr = KH.roll_track(R, n, True, times)
    assert max(abs(b - a) for a, b in zip(tr, tr[1:])) < math.radians(30)   # no full turn between neighbouring keys
