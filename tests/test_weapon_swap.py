"""Swapping the weapon of a one-handed attack: swing_arm's pinned frames, eased path, path hold and other-arm weights; the
fist against the grip (one_hand_weapon) and the audit's finger_curl; the pose diff. Rules on synthetic data, no Blender.
python -m pytest tests  (or: python tests/test_weapon_swap.py)"""
import json, os, sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for d in ("pipeline", os.path.join("pipeline", "lib"), os.path.join("pipeline", "recipes"), os.path.join("pipeline", "checks")):
    sys.path.insert(0, os.path.join(ROOT, d))
import audit_metrics as AM
import one_hand_weapon as OW
import pose_diff as PD
import schema_check
import swing_arm as SA
from test_swing_arm import N, clip, consts, frame

EXAMPLE = os.path.join(ROOT, "examples", "weapon_swap.example.json")


def with_arm(c, C, swivel):
    """The clip with the arm it was made with: the weapon on the path without roll, the elbow at `swivel` [frames]."""
    s = [SA.solve(C, frame(c, f), swivel[f], 0.0) for f in range(N)]
    return dict(c, Bu=np.array([x["Bu"][0] for x in s]), Bf=np.array([x["Bf0"][0] for x in s]), Bh=np.array([x["H3"][0] for x in s]),
                E=np.array([x["E"][0] for x in s]), W=np.array([x["W"][0] for x in s]))


def test_turn_of_and_end_weights():
    ang, ax = SA.turn_of(SA.rot(SA.unit([1.0, 2, 3]), 40.0))
    assert abs(ang - 40) < 1e-9 and np.allclose(ax, SA.unit([1.0, 2, 3])) and SA.turn_of(np.eye(3))[0] == 0
    w = SA.end_weights(56, 4)
    assert w[0] == w[55] == 1 and w[4] > 0 and w[5] == 0 and w[50] == 0 and w[51] > 0 and np.allclose(w, w[::-1])
    assert np.all(np.diff(w[:6]) < 0) and abs(w[2] - SA.smoothstep(0.6)) < 1e-12
    assert np.allclose(SA.end_weights(5, 0), [1, 0, 0, 0, 1])


def test_ease_path_eases_from_the_pinned_frames_real_weapon_into_the_path():
    n = 21; G3 = np.tile(np.eye(3), (n, 1, 1)); Gt = np.stack([np.arange(n) * 0.01, np.zeros(n), np.zeros(n)], 1)
    real3 = np.tile(SA.rot(SA.X, 40.0), (n, 1, 1)); realt = Gt + [0.0, 0.03, 0.0]
    E3, Et, off = SA.ease_path(G3, Gt, real3, realt, [0], 5, True)
    assert abs(off[0][0] - 40) < 1e-9 and abs(off[0][1] - 3) < 1e-9
    assert np.allclose(E3[0], real3[0]) and np.allclose(Et[0], realt[0]) and np.allclose(E3[20], real3[20])   # pinned; the loop's last frame too
    for k in range(1, 5):
        s = 1 - SA.smoothstep(k / 5)
        for f in (k, 20 - k):                                              # both sides of frame 0, round the loop
            assert np.allclose(Et[f] - Gt[f], [0, 0.03 * s, 0]) and abs(SA.turn_of(E3[f])[0] - 40 * s) < 1e-9
    assert np.allclose(E3[5:16], G3[5:16]) and np.allclose(Et[5:16], Gt[5:16])                                  # the rest of the path stays
    E3, Et, _ = SA.ease_path(G3, Gt, real3, realt, [0], 5, False)
    assert np.allclose(Et[16:], Gt[16:]) and not np.allclose(Et[1], Gt[1])                                     # one-shot: nothing wraps
    E3, Et, _ = SA.ease_path(G3, Gt, real3, realt, [0], 0, True)
    assert np.allclose(Et[1:20], Gt[1:20]) and np.allclose(Et[0], realt[0])                                    # no ease: the jump stays in one frame


def test_a_pinned_frame_keeps_the_clips_arm_and_the_sequence_passes_through_it():
    C, c = consts(), clip(); free = SA.plan(c, C, loop=True)
    sw = free["swivel"].copy(); sw[[0, N - 1]] += 65                       # the clip's arm on frame 0: the elbow 65 deg off the solver's choice
    c2 = with_arm(c, C, sw); O = SA.plan(c2, C, loop=True, pins=[0])
    for k, src in (("Bu", "Bu"), ("Bf", "Bf"), ("Bh", "Bh"), ("E", "E"), ("W", "W")):
        assert np.allclose(O[k][0], c2[src][0]) and np.allclose(O[k][-1], c2[src][-1]), k                       # frame 0 and the loop's end
    assert O["pinned"].tolist() == [True] + [False] * (N - 2) + [True] and abs(O["held"][0][0]) < 1e-6 and O["held"][0][1] < 1e-6
    assert abs(SA.fold(O["swivel"][0] - sw[0])) < 1e-6 and O["roll"][0] == 0
    assert np.allclose(O["W"] + O["Bh"] @ C["grip_t"], c["Gt"], atol=1e-9)                                     # same hold: the path is untouched
    assert not np.allclose(O["E"][0], free["E"][0]) and np.abs(SA.fold(np.diff(O["swivel"]))).max() <= 60       # and the neighbours lead to it
    try: SA.plan(c2, C, loop=True, pins=[N]); raise AssertionError("accepted")
    except ValueError as e: assert "outside the action" in str(e)


def test_a_new_hold_keeps_the_blade_path_and_eases_at_the_pinned_frame():
    C, c = consts(), clip(); c2 = with_arm(c, C, np.zeros(N))             # the clip as made with the old hold
    new, _ = SA.grip_frame([[0, 0, 1, 0.02], [0.94, 0.342, 0, 0.09], [-0.342, 0.94, 0, 0.0], [0, 0, 0, 1]], [[0, 0, -0.1], [0, 0, 0.1]], [0, 0, 0.8], [1, 0, 0])
    C2 = dict(C, grip3=new[:3, :3], grip_t=new[:3, 3])                     # the path (c["G3"], c["Gt"]) was read with the old hold
    O = SA.plan(c2, C2, loop=True, pins=[0], ease=3)
    assert O["held"][0][0] > 5 and O["held"][0][1] > 1                     # the pinned arm holds the new weapon off the path
    assert np.allclose(O["W"] + O["Bh"] @ C2["grip_t"], O["Gt"], atol=1e-9) and np.allclose((O["Bh"] @ C2["grip3"])[:, :, 2], O["G3"][:, :, 2], atol=1e-9)
    assert np.allclose(O["Gt"][3:N - 3], c["Gt"][3:N - 3]) and np.allclose(O["G3"][3:N - 3], c["G3"][3:N - 3])  # past the ease: the accepted path
    off = np.linalg.norm(O["Gt"] - c["Gt"], axis=1)
    assert off[0] > off[1] > off[2] > 0 and off[N - 2] > off[N - 3] > 0 and np.allclose(O["Bh"][0], c2["Bh"][0])


def test_grip_profile_measures_skin_inside_and_off_the_grip():
    a, b = np.array([0.1, 0.2, 0.0]), np.array([0.1, 0.2, 0.1]); ang = np.radians(np.arange(0, 360, 5)); z = np.arange(0, 0.1001, 0.0025)
    ring = lambda r, zz: np.stack([0.1 + r * np.cos(ang), 0.2 + r * np.sin(ang), np.full(len(ang), zz)], 1)   # noqa: E731
    P = OW.grip_profile(np.concatenate([ring(0.02, zz) for zz in z]), a, b)
    assert P.shape == (20, 24) and np.allclose(P, 0.02)
    d = OW.grip_depth(P, np.array([[0.115, 0.2, 0.05], [0.1, 0.23, 0.05], [0.1, 0.2, 0.2], [0.1, 0.2, -0.01]]), a, b)
    assert np.allclose(d[:2], [-0.005, 0.01]) and np.isnan(d[2:]).all()   # inside, off the surface, past either end
    half = OW.grip_profile(np.concatenate([ring(0.02, zz)[:36] for zz in z]), a, b)   # a surface on one side only
    assert np.isnan(OW.grip_depth(half, np.array([[0.1, 0.17, 0.05]]), a, b)[0]) and abs(OW.grip_depth(half, np.array([[0.1, 0.23, 0.05]]), a, b)[0] - 0.01) < 1e-9
    co = np.array([[0.0, 0, 0], [0.02, 0, 0], [0, 0.02, 0]]); pts = OW.surface_points(co, [(0, 1, 2)])
    assert len(pts) > 10 and np.allclose(pts[:, 2], 0) and (pts.sum(1) <= 0.02 + 1e-12).all() and pts.min() >= 0
    assert len(OW.surface_points(co * 0.1, [(0, 1, 2)])) == 3            # a triangle smaller than the step: its corners


def test_finger_row_and_the_fist_line():
    nan = np.nan
    f = OW.finger_row([("index.1", 37.2, [0.021, 0.03]), ("index.2", 71.9, [-0.004, 0.011, nan]), ("index_end", 0.0, [nan, nan])])
    assert f["flexion_deg"] == 109 and f["inside_cm"] == 0.4 and f["gap_cm"] == 2.1
    assert f["bones"]["index.2"] == {"flexion_deg": 72, "inside_cm": 0.4, "gap_cm": 0.0} and f["bones"]["index_end"]["gap_cm"] is None
    g = OW.finger_row([("pinky.1", 90.0, [-0.025]), ("pinky.2", 100.0, []), ("pinky.3", 95.0, [])])
    line = OW.fist_line({"index.1": f, "pinky.1": g})
    assert "bend 109-285 deg" in line and "2.5 cm inside the grip (pinky.1)" in line and "2.1 cm off it (index.1)" in line
    assert OW.fist_line({}) == "no finger bones below the hand"


def test_finger_curl_limit_sits_between_the_two_fists():
    lim = AM.METRICS["finger_curl_R"][0]
    assert 160 < lim < 270 and AM.METRICS["finger_curl_L"][0] == lim     # the author's fist 58-109, a computed wrap 154-160; the rejected one 270-297
    assert AM.finger_curl({"index.1": [89, 100, 108], "thumb.1": [26, 0, 53], "ring.1": [0, 70, 0]}) == ("index.1", 297.0)
    reps = [{"recipe": "one_hand_weapon", "action": "attack", "weapon": "sword", "hand": "R"}, {"recipe": "swing_arm", "action": "attack", "hand": "R"},
            {"recipe": "one_hand_weapon", "action": "idle", "weapon": "sword", "hand": "L"}, "not a report"]
    assert AM.hands_with_weapon(reps, "attack") == {"R"} and AM.hands_with_weapon(reps, "walk") == set()   # swing_arm puts no weapon there
    assert AM.NEEDS["finger_curl_L"] == ("hand.left", "fingers")


def test_pose_diff_lists_the_changed_bones_most_changed_first():
    q = lambda deg: (float(np.cos(np.radians(deg) / 2)), float(np.sin(np.radians(deg) / 2)), 0.0, 0.0)   # noqa: E731
    a = {0: {"hand": q(10), "index.1": q(37), "spine": q(5), "old": q(0)}, 14: {"hand": q(20), "index.1": q(86), "spine": q(5), "old": q(0)}}
    b = {0: {"hand": q(10.4), "index.1": q(89), "spine": tuple(-x for x in q(5)), "new": q(0)}, 14: {"hand": q(20), "index.1": q(89), "spine": q(5), "new": q(0)},
         20: {"hand": q(99)}}
    d = PD.diff(a, b, threshold=1.0)
    assert d["frames"] == [0, 14] and [r[0] for r in d["rows"]] == ["index.1", "hand", "spine"]
    assert abs(d["rows"][0][1] - 52) < 1e-6 and d["rows"][0][2] == 0 and abs(d["rows"][1][1] - 0.4) < 1e-6 and d["rows"][2][1] < 1e-4   # -q is the same turn
    assert d["over"] == ["index.1"] and d["only_a"] == ["old"] and d["only_b"] == ["new"]
    text = "\n".join(PD.lines(d, 1.0))
    assert "1 of 3 bones over 1 deg" in text and "CHANGED index.1" in text and "hand " not in text.split("CHANGED")[1].split("\n", 1)[1].split("only")[0]
    assert "only in the first source: old" in text and PD.diff(a, a)["over"] == []


def test_weapon_swap_example_and_the_new_inputs_in_the_schema():
    M = json.load(open(EXAMPLE, encoding="utf-8")); assert schema_check.problems(M, "motion") == []
    sw = M["recipe"][0]; P = SA.weapon_inputs(M)
    assert P["in_hand"] == M["recipe"][1]["in_hand"] and sw["path_hold"]["in_hand"] != P["in_hand"]              # two holds: the path's and the new one
    old, _ = SA.grip_frame(sw["path_hold"]["in_hand"], sw["path_hold"]["grip"], sw["path_hold"]["tip"], P["edge"])
    assert np.allclose(old[:3, 2], [1, 0, 0])                              # the old blade lay along the hand bone's X
    sw["pin"] = [0, -1]; sw["ease_frames"] = 2.5; sw["path_hold"] = {"grip": [[0, 0, 0], [0, 1, 0]]}; sw["other_arm_blend"] = {"frame": 0, "side": "left"}
    p = "\n".join(schema_check.problems(M, "motion"))
    for bit in ("pin[1]", "ease_frames", "path_hold", "other_arm_blend"): assert bit in p, (bit, p)


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
