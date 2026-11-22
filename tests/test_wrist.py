"""The wrist of a weapon hand in line with the forearm (pipeline/lib/wrist.py): the hand's axes from its fingers, the bend
split into flexion and deviation, the audit's limits, and swing_arm's cost by direction. Synthetic data, no Blender.
python -m pytest tests  (or: python tests/test_wrist.py)"""
import json, os, sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for d in ("pipeline", os.path.join("pipeline", "lib"), os.path.join("pipeline", "recipes")): sys.path.insert(0, os.path.join(ROOT, d))
import audit_metrics as AM
import schema_check
import swing_arm as SA
import wrist
from test_swing_arm import N, clip, consts, frame

X, Y, Z = np.eye(3)
KNUCKLES = np.array([[-0.03, 0.09, 0.0], [-0.01, 0.10, 0.0], [0.01, 0.095, 0.0], [0.03, 0.085, 0.0]])   # a right hand, palm down: index at -X


def test_hand_axes_come_from_the_knuckle_line_and_the_thumbs_side():
    r, p = wrist.hand_axes(Y, [-0.03, 0.03, -0.02], KNUCKLES, "R")       # the thumb starts nearer the palm (-Z) than the knuckles
    assert np.allclose(r, -X) and np.allclose(p, -Z)                       # radial along the knuckles, not tilted by the thumb; palm down
    r, p = wrist.hand_axes(Y, [0.03, 0.03, -0.02], KNUCKLES * [-1, 1, 1], "L")
    assert np.allclose(r, X) and np.allclose(p, -Z)                        # the mirrored hand: its palm faces down too
    r, p = wrist.hand_axes(Y, [-0.03, 0.03, 0.0], KNUCKLES[1:2], "R")     # one other finger: the thumb's own offset
    assert np.allclose(r, -X) and wrist.hand_axes(Y, [-0.03, 0.03, 0], np.zeros((0, 3)), "R") is None
    r, p = wrist.hand_axes([0.0, 2.0, 0.0], [-0.03, 0.5, -0.02], KNUCKLES + [0, 0.4, 0], "R")
    assert np.allclose(r, -X) and abs(r @ Y) < 1e-12 and abs(p @ Y) < 1e-12 and abs(r @ p) < 1e-12   # across the hand, whatever its length


def test_split_shares_the_bend_out_by_its_direction():
    radial, palm = -X, -Z
    turn = lambda toward, deg: SA.rot(np.cross(Y, toward), deg)            # noqa: E731  the hand's own axis swung toward a direction
    f, d = wrist.split(turn(palm, 30.0), radial, palm); assert abs(f - 30) < 1e-9 and abs(d) < 1e-9          # flexion
    f, d = wrist.split(turn(-palm, 24.0), radial, palm); assert abs(f + 24) < 1e-9 and abs(d) < 1e-9         # extension
    f, d = wrist.split(turn(-radial, 73.0), radial, palm); assert abs(d + 73) < 1e-9 and abs(f) < 1e-9       # toward the little finger
    f, d = wrist.split(turn(SA.unit(palm - radial), 60.0), radial, palm)
    assert abs(np.hypot(f, d) - 60) < 1e-9 and abs(f - 60 / np.sqrt(2)) < 1e-9 and d < 0                    # the bend, in quadrature
    f, d = wrist.split(turn(-radial, 100.0) @ SA.rot(Y, 50.0), radial, palm)
    assert abs(d + 100) < 1e-9 and abs(f) < 1e-9                           # past a right angle it still reads; a twist does not change it
    many = np.stack([turn(palm, 10.0), turn(radial, 20.0)]); f, d = wrist.split(many, radial, palm)
    assert np.allclose(f, [10, 0]) and np.allclose(d, [0, 20])


def test_neutral_is_the_rest_pose():
    fr, hr = SA.rot(Z, 90.0), SA.rot(Z, 90.0) @ SA.rot(X, 15.0); move = SA.rot(SA.unit([1.0, 2, 3]), 77.0)
    assert np.allclose(wrist.neutral(fr, hr, move @ fr, move @ hr), np.eye(3))                  # the whole arm moved: the wrist did not
    bend = SA.rot(X, 30.0); assert np.allclose(wrist.neutral(fr, hr, move @ fr, move @ hr @ bend), bend)


def test_wrist_limits_pass_the_authors_hand_posed_frames_and_fail_the_circled_one():
    flex, dev = AM.METRICS["wrist_flexion_R"][0], AM.METRICS["wrist_deviation_R"][0]
    posed = [(-24.3, -16.4), (-39.5, -5.3), (-43.2, -5.5), (-20.3, 19.9), (-23.4, -6.4)]      # his frame 19; his keys 0, 14, 20, 28
    assert all(abs(f) <= flex and abs(d) <= dev for f, d in posed)
    for f, d in ((-4.5, -73.6), (23.5, -87.9), (18.9, -85.1)): assert abs(d) > dev             # 9i frames 19, 26, 27
    assert 73.7 < AM.METRICS["wrist_bend_R"][0]                                                # the one cone passed frame 19
    assert AM.METRICS["wrist_flexion_L"][0] == flex and AM.METRICS["wrist_deviation_L"][0] == dev and dev < flex


def split_consts():
    C = consts(); C.update(radial=X, palm=Z, wrist_split=True); return C


def test_roll_cost_by_direction_is_stricter_sideways():
    C = split_consts(); zero = np.zeros(1)
    cone = SA.roll_cost(C, zero, zero, np.array([60.0]))
    side = SA.roll_cost(C, zero, zero, np.array([60.0]), (np.array([0.0]), np.array([-60.0])))
    flexed = SA.roll_cost(C, zero, zero, np.array([60.0]), (np.array([60.0]), np.array([0.0])))
    assert side[0] > flexed[0] > cone[0]                                   # the same 60 deg: inside the cone, far over as a sideways bend
    inline = SA.roll_cost(C, zero, zero, np.array([20.0]), (np.array([-20.0]), np.array([0.0])))
    assert inline[0] < 2 * SA.roll_cost(C, zero, zero, np.array([20.0]))[0] + 1


def test_plan_with_the_split_wrist_keeps_the_path_and_straightens_the_wrist():
    c = clip(); cone = SA.plan(c, dict(split_consts(), wrist_split=False), loop=True); C = split_consts(); O = SA.plan(c, C, loop=True)
    assert np.allclose(O["W"] + O["Bh"] @ C["grip_t"], c["Gt"], atol=1e-9) and np.allclose((O["Bh"] @ C["grip3"])[:, :, 2], c["G3"][:, :, 2], atol=1e-9)
    m = lambda o: SA.measure(C, o["Bs"], o["Bu"], o["Bf"], o["Bh"], o["S"], o["E"], o["W"], c["head"])   # noqa: E731
    a, b = m(cone), m(O)
    assert np.abs(b["wrist_deviation"]).max() < np.abs(a["wrist_deviation"]).max()             # the fist no longer hangs to a side
    assert np.allclose(np.hypot(b["wrist_flexion"], b["wrist_deviation"]), b["wrist_bend"], atol=1e-6)
    assert "wrist_flexion" not in SA.measure(consts(), O["Bs"], O["Bu"], O["Bf"], O["Bh"], O["S"], O["E"], O["W"], c["head"])   # no axes: the cone only
    over = SA.over_targets({"upper_arm_twist": np.zeros(2), "forearm_roll": np.zeros(2), "wrist_twist": np.zeros(2), "wrist_bend": np.array([90.0, 40.0]),
                            "wrist_flexion": np.array([30.0, -40.0]), "wrist_deviation": np.array([-10.0, 20.0]), "swivel": np.zeros(2),
                            "elbow_above_cm": np.zeros(2), "hand_high": np.zeros(2, bool)}, SA.TARGETS, split=True)
    assert over == [[], ["wrist_flexion", "wrist_deviation"]]             # the cone is not counted next to its own split


def test_a_locked_elbow_costs_and_the_weight_switches_it_off():
    C, c = consts(), clip(); c["Gt"][0] = c["s0"][0] + [0.0, -0.595, 0.0] + c["G3"][0] @ C["grip3"].T @ C["grip_t"]   # the wrist almost at arm's length
    fr = frame(c, 0); s = SA.solve(C, fr, [0.0], [0.0]); ang = SA.elbow_angle(s["S"], s["E"], s["W"])[0]
    off = dict(C, weights=dict(C["weights"], elbow_straight=0))
    assert ang > 165 and abs(SA.cost(C, fr, s)[0] - SA.cost(off, fr, s)[0] - ((ang - 160) / 10) ** 2) < 1e-9
    bent = SA.solve(C, frame(c, 3), [0.0], [0.0]); assert SA.elbow_angle(bent["S"], bent["E"], bent["W"])[0] < 160
    assert abs(SA.cost(C, frame(c, 3), bent)[0] - SA.cost(off, frame(c, 3), bent)[0]) < 1e-12   # a bent arm pays nothing
    assert abs(SA.elbow_angle(np.zeros(3), X, 2 * X) - 180) < 1e-6 and abs(SA.elbow_angle(np.zeros(3), X, X + Y) - 90) < 1e-9


def test_schema_takes_the_wrist_switch_and_the_new_targets():
    M = json.load(open(os.path.join(ROOT, "examples", "swing_arm.example.json"), encoding="utf-8")); sw = M["recipe"][0]
    sw["wrist"] = "cone"; sw["targets"] = {"wrist_flexion": 30, "wrist_deviation": 15, "elbow_angle": 165}; sw["weights"] = {"elbow_straight": 0}
    assert schema_check.problems(M, "motion") == []
    sw["wrist"] = "loose"; sw["targets"]["wrist_deviation"] = 0; sw["weights"]["elbow"] = 1
    p = "\n".join(schema_check.problems(M, "motion"))
    for bit in ("wrist", "wrist_deviation", "weights"): assert bit in p, (bit, p)
    assert N > 3


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
