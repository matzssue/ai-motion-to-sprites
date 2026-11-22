"""swing_arm's strike options (pin_toward, reach, wrist_anatomical, wrist_twist_cap, forearm_clear) on the synthetic arm of
test_swing_arm.py, no Blender; and that with none of them the recipe's output is what it was before they existed.
python -m pytest tests  (or: python tests/test_swing_arm_strike.py)"""
import json, os

import numpy as np

import test_swing_arm as B
from test_swing_arm import SA

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
KNIGHT = os.path.join(ROOT, "examples", "knight", "attack.json")
# plan() on test_swing_arm's clip before the strike options existed (develop a30df9f); swivel -90 on every frame
GOLDEN = {"loop": {"roll": [-45, -33.75, -11.25, 0, -11.25, -33.75, -45, -45, -45, -45, -45, -45, -45],
                   "forearm": [-45, -15, 0, 0, -15, -30, -45, -60, -75, -75, -75, -60, -45], "Bh_sum": 56.65597993831429},
          "open": {"roll": [-45, -33.75, -11.25, 0, -11.25, -33.75, -45, -45, -45, -45, -45, -45, -45],
                   "forearm": [-30, -15, 0, 0, -15, -30, -45, -60, -75, -75, -75, -60, -45], "Bh_sum": 56.65597993831429},
          "pin": {"roll": [0, 0, 0, 0, -11.25, -33.75, -45, -45, -45, -45, -33.75, -11.25, 0],
                  "forearm": [-45, -15, 0, 0, -15, -30, -45, -60, -75, -75, -75, -60, -45], "Bh_sum": 57.18506187897444}}


def pinned_clip(C):
    c = B.clip(); O = SA.plan(c, C, loop=True)
    return dict(c, **{k: O[k] for k in ("Bu", "Bf", "Bh", "E", "W")})


def test_without_the_options_the_output_is_unchanged():
    C = B.consts()
    for name, c, kw in (("loop", B.clip(), {}), ("open", B.clip(), {"loop": False}), ("pin", pinned_clip(C), {"pins": [0], "ease": 3})):
        O = SA.plan(c, C, **kw); g = GOLDEN[name]
        assert np.allclose(O["swivel"], -90) and np.allclose(O["roll"], g["roll"]) and np.allclose(O["forearm"], g["forearm"]), name
        assert abs(float(np.abs(O["Bh"]).sum()) - g["Bh_sum"]) < 1e-9 and O["toward"] is None and O["reached"] == [], name


def test_wrist_twist_cap_costs_100_per_5_deg_over():
    C = B.consts(); base = SA.roll_cost(C, 0.0, np.array([60.0, 73.0]), 0.0)
    C["wrist_twist_cap"] = 68; capped = SA.roll_cost(C, 0.0, np.array([60.0, 73.0]), 0.0)
    assert np.allclose(capped - base, [0, 100])


def test_wrist_anatomical_reads_flexion_and_deviation_about_the_hand_axes_on_its_frames():
    C = B.consts(); I = np.eye(3)[None]
    fl, dv = SA.axis_flex_dev(C, I, SA.rot(SA.X, 30.0)[None]); assert np.allclose([fl[0], dv[0]], [30, 0])
    fl, dv = SA.axis_flex_dev(C, I, SA.rot(SA.Z, -20.0)[None]); assert np.allclose([fl[0], dv[0]], [0, 20])
    c = B.clip(); s = SA.solve(C, dict(B.frame(c, 3), f=3), [-90.0, 0.0], [0.0, 90.0]); rho = np.arange(-180, 180, 30)
    plain = SA.forearm_cost(C, s, rho)
    C["anatomical"] = {"flexion": 70, "deviation": 30, "frames": [5, 8]}
    assert np.allclose(SA.forearm_cost(C, s, rho), plain)                      # frame 3 is outside the span
    C["anatomical"]["frames"] = [2, 4]; anat = SA.forearm_cost(C, s, rho)
    Bf, pr, wt, wb = SA.forearm(C, s, rho); fl, dv = SA.axis_flex_dev(C, Bf, s["H3"][:, None]); w = C["weights"]
    want = w["forearm_roll"] * SA.soft(pr, 80) + w["wrist"] * (SA.soft(wt, 60) + SA.soft(dv, 30) + SA.soft(fl, 70))
    assert np.allclose(anat, want) and not np.allclose(anat, plain)


def test_forearm_clear_costs_weapon_points_near_the_arm_on_its_frames():
    C = B.consts(); C["grip3"] = np.eye(3); C["clear_pts"] = np.array([[0.04, 0.0, 0.0], [0.5, 0.0, 0.0]])
    s = {"S": np.array([[0.0, 0, 0]]), "E": np.array([[0.0, 0.3, 0]]), "W": np.array([[0.0, 0.6, 0]]), "H3": np.eye(3)[None]}
    fr = {"Gt": np.array([0.0, 0.45, 0.0]), "f": 7}                             # first point 4 cm off the forearm, the other far
    assert np.allclose(SA.clear_dist(C, fr["Gt"], s), [[0.04, 0.5]])
    C["forearm_clear"] = {"radius_cm": 9, "weight": 200, "frames": [6, 9]}
    assert np.allclose(SA.clear_cost(C, fr, s), 200 * (5 / 9) ** 2)
    assert SA.clear_cost(C, dict(fr, f=10), s) == 0.0
    fr["Gt"] = np.array([0.0, 0.62, 0.0]); C["forearm_clear"]["past_wrist_cm"] = 0   # past the wrist: only the past_wrist_cm part counts
    assert np.allclose(SA.clear_dist(C, fr["Gt"], s), [[np.hypot(0.04, 0.02), np.hypot(0.5, 0.02)]])


def test_helmet_distance_as_the_s_and_se_cameras_see_it():
    C = B.consts(); C["guard"], C["blade"] = 0.2, 0.8; head = np.array([0.0, 0.0, 1.75]); hc = head - SA.UP * SA.HELMET_DOWN
    d = SA.unit(np.array([0.0, -np.cos(np.radians(30)), np.sin(np.radians(30))]))   # the S camera's line of sight, toward it
    on = SA.helmet_cm(C, head, SA.X, (hc + d * 0.3 - SA.X * 0.5)[None])           # blade crosses the helmet's line in front of it
    behind = SA.helmet_cm(C, head, SA.X, (hc - SA.Y * -0.5 - SA.Z * 0.6 - SA.X * 0.5)[None] - d * 2)
    assert on[0] < 1e-6 and behind[0] == 99.0


def test_pin_toward_moves_a_share_of_the_way_over_a_smoothstep():
    c = B.clip(); tw = {"frame": 6, "G3": SA.rot(SA.Z, 40.0) @ c["G3"][6], "Gt": c["Gt"][6] + [0.1, 0, 0], "t": 0.75, "ease": 2}
    G3, Gt, (deg, cm) = SA.toward_path(c["G3"], c["Gt"], tw, True)
    assert abs(deg - 40) < 1e-6 and abs(cm - 10) < 1e-6
    moved = np.linalg.norm(Gt - c["Gt"], axis=1) * 100
    assert np.allclose(moved[[4, 5, 6, 7, 8]], 7.5 * SA.smoothstep(1 - np.abs(np.arange(-2, 3)) / 3)) and np.allclose(np.delete(moved, [4, 5, 6, 7, 8]), 0)
    ang, _ = SA.turn_of(G3[6] @ c["G3"][6].T); assert abs(ang - 30) < 1e-6
    tw["t"] = 1.0; G3, Gt, _ = SA.toward_path(c["G3"], c["Gt"], tw, True)
    assert np.allclose(G3[6], tw["G3"]) and np.allclose(Gt[6], tw["Gt"])
    try: SA.toward_path(c["G3"], c["Gt"], dict(tw, frame=40), True); raise AssertionError("accepted")
    except ValueError as e: assert "frame 40" in str(e)


def test_reach_moves_the_span_by_one_offset_with_ramps():
    C = B.consts(); c = B.clip(); c["Gt"][5:8] += [0.0, -0.25, 0.0]   # grip far ahead on 5-7: the arm locks straight there
    span = {"frames": [5, 6, 7], "rolls": {"5": 0, "6": 0, "7": 0}, "cap_cm": 12, "grid_cm": 6, "ramp": [0.5], "elbow_soft": [150, 3]}
    O = SA.plan(c, C, loop=True, reach=[span]); (fs, V, cost, cost0), = O["reached"]
    assert fs == [5, 6, 7] and cost < cost0 and np.linalg.norm(V) <= 0.12 + 1e-9 and np.linalg.norm(V) > 0
    d = O["Gt"] - SA.edit_path(c["G3"], c["Gt"], c["s0"], c["head"], None)[1]
    assert np.allclose(d[[5, 6, 7]], V) and np.allclose(d[[4, 8]], V * 0.5) and np.allclose(np.delete(d, [4, 5, 6, 7, 8], 0), 0)
    assert np.allclose(O["G3"], c["G3"])                                       # the blade direction stays
    tiny = dict(span, cap_cm=1)                                                 # nothing on the grid within the cap: no offset
    assert np.allclose(SA.plan(c, C, loop=True, reach=[tiny])["reached"][0][1], 0)
    try: SA.plan(c, C, reach=[dict(span, rolls={"5": 0})]); raise AssertionError("accepted")
    except ValueError as e: assert "no `rolls` for frames [6, 7]" in str(e)


def test_reach_rejects_an_offset_that_brings_the_weapon_into_the_arm():
    C = B.consts(); c = B.clip(); c["Gt"][5:8] += [0.0, -0.25, 0.0]
    span = {"frames": [5, 6, 7], "rolls": {"5": 0, "6": 0, "7": 0}, "cap_cm": 12, "grid_cm": 6, "elbow_soft": [150, 3]}
    free = SA.plan(c, C, reach=[span])["reached"][0]
    C["clear_pts"] = np.array([[0.0, 0.0, 0.0]])                               # the grip point: always within 50 cm of the arm
    rejected = SA.plan(c, C, reach=[dict(span, clear_reject_cm=50)])["reached"][0]
    assert abs(rejected[2] - free[2] - 3 * SA.REJECT) < 1e-6 and np.allclose(rejected[1], free[1])   # every offset pays it on all three
    C["clear_pts"] = np.array([[0.0, 0.0, 0.6]])                               # far up the blade: nothing rejected
    assert abs(SA.plan(c, C, reach=[dict(span, clear_reject_cm=1)])["reached"][0][2] - free[2]) < 1e-9


def test_the_knight_example_names_every_option_and_passes_the_schema():
    import schema_check
    M = json.load(open(KNIGHT, encoding="utf-8")); assert schema_check.problems(M, "motion") == []
    sw = M["recipe"][0]
    for k in ("pin_toward", "reach", "wrist_anatomical", "wrist_twist_cap", "forearm_clear", "clear_points", "guard"): assert k in sw, k
    bad = json.loads(json.dumps(M)); b = bad["recipe"][0]
    del b["reach"][0]["rolls"]; b["wrist_anatomical"]["frames"] = [14]; del b["pin_toward"]["poses"]; b["forearm_clear"]["radius"] = 9
    p = "\n".join(schema_check.problems(bad, "motion"))
    for bit in ("$.recipe[0].reach[0]", "'rolls' is a required property", "$.recipe[0].wrist_anatomical.frames", "'poses' is a required property",
                "$.recipe[0].forearm_clear: Additional properties"): assert bit in p, (bit, p)


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
