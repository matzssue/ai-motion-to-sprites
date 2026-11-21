"""swing_arm recipe (pipeline/recipes/swing_arm.py): its rules on a synthetic arm, no Blender; and a motion file's list of
recipes (schema, order, the files chain.py writes).
python -m pytest tests  (or: python tests/test_swing_arm.py)"""
import json, os, sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for d in ("pipeline", os.path.join("pipeline", "lib"), os.path.join("pipeline", "recipes")):
    sys.path.insert(0, os.path.join(ROOT, d))
import recipe_list
import schema_check
import swing_arm as SA

EXAMPLE = os.path.join(ROOT, "examples", "swing_arm.example.json")
N = 13   # frames of the synthetic clip; the last repeats the first
REST = SA.rot(SA.Z, 90.0)   # every arm bone at rest: its Y along the character's right (-X)


def consts():
    """A right arm of two 30 cm bones, in a T-pose at rest (see REST), the elbow folding forward, a sword across the palm."""
    grip, blade = SA.grip_frame([[0, 0, 1, 0.0], [1, 0, 0, 0.08], [0, 1, 0, 0.0], [0, 0, 0, 1]], [[0, 0, -0.1], [0, 0, 0.1]], [0, 0, 0.8], [1, 0, 0])
    return {"R_su": np.eye(3), "R_uf": np.eye(3), "R_fh": np.eye(3), "L1": 0.3, "L2": 0.3, "hinge": np.stack([SA.Z, SA.Y, np.cross(SA.Z, SA.Y)], -1),
            "grip3": grip[:3, :3], "grip_t": grip[:3, 3], "blade": blade, "targets": dict(SA.TARGETS), "weights": dict(SA.WEIGHTS),
            "grid": {"swivel": 30, "roll": 45, "forearm": 15}}


def clip():
    """The grip circling in front of the right shoulder, the blade swaying; frame N-1 = frame 0."""
    a = 2 * np.pi * np.arange(N) / (N - 1); s0 = np.array([-0.2, 0.0, 1.4])
    Gt = s0 + np.stack([0.05 * np.cos(a), -0.3 + 0 * a, -0.1 + 0.15 * np.sin(a)], 1)
    G3 = SA.rot(SA.X, 60 + 30 * np.sin(a))
    one = lambda v: np.tile(np.asarray(v, float), (N, 1))   # noqa: E731
    return {"G3": G3, "Gt": Gt, "c0": one([-0.05, 0, 1.4]), "s0": one(s0), "Bs": np.tile(REST, (N, 1, 1)),
            "head": one([0, 0, 1.75]), "other": one([0.2, 0, 1.4])}


def frame(c, f, turn=0.0):
    return dict({k: c[k][f] for k in ("c0", "s0", "Bs", "head", "other", "G3", "Gt")}, turn=turn)


def test_twist_bend_separates_the_turn_about_the_bone_from_the_bend():
    tw, bd = SA.twist_bend(SA.rot(SA.Y, np.array([30.0, -170.0, 0.0])))
    assert np.allclose(tw, [30, -170, 0]) and np.allclose(bd, 0, atol=1e-5)
    tw, bd = SA.twist_bend(SA.rot(SA.X, 40.0))
    assert abs(tw) < 1e-9 and abs(bd - 40) < 1e-6
    tw, bd = SA.twist_bend(SA.rot(SA.Y, 30.0) @ SA.rot(SA.Z, 50.0))
    assert abs(tw - 30) < 1e-6 and abs(bd - 50) < 1e-6


def test_grip_frame_follows_the_weapon_mesh():
    G, blade = SA.grip_frame([[0, 0.5, 0, 0.329], [0.5, 0, 0, 0.105], [0, 0, -0.5, -0.004], [0, 0, 0, 1]],
                             [[0, -0.8, 0], [0, -0.5, 0]], [0, 0.99, 0], [1, 0, 0])
    assert np.allclose(G[:3, 3], [0.004, 0.105, -0.004]) and abs(blade - 0.82) < 1e-9   # mid-grip; a half-size mesh
    assert np.allclose(G[:3, 2], [1, 0, 0]) and np.allclose(G[:3, 0], [0, 1, 0])        # blade, edge in the hand's frame
    assert abs(np.linalg.det(G[:3, :3]) - 1) < 1e-9
    for tip, edge in (([0, -0.65, 0], [1, 0, 0]), ([0, 0.99, 0], [0, 1, 0])):   # tip on the grip; edge along the blade
        try: SA.grip_frame(np.eye(4), [[0, -0.8, 0], [0, -0.5, 0]], tip, edge); raise AssertionError("accepted")
        except ValueError: pass


def test_weapon_inputs_come_from_the_one_hand_weapon_entry():
    M = json.load(open(EXAMPLE, encoding="utf-8"))
    P = SA.weapon_inputs(M)
    assert P["hand"] == "right" and P["in_hand"] == M["recipe"][1]["in_hand"] and P["grip"] == M["recipe"][1]["grip"]
    M["recipe"][0]["grip"] = [[0, 0, -0.7], [0, 0, -0.6]]
    assert SA.weapon_inputs(M)["grip"] == [[0, 0, -0.7], [0, 0, -0.6]]   # its own value wins
    try: SA.weapon_inputs({"recipe": {"name": "swing_arm", "tip": [0, 0, 1], "edge": [1, 0, 0]}}); raise AssertionError("accepted")
    except ValueError as e: assert "in_hand, grip" in str(e)


def test_solve_holds_the_grip_with_the_bone_lengths_kept():
    C, c = consts(), clip(); phi = np.array([0.0, 40, -90, 170, 0, 0]); roll = np.array([0.0, 0, 0, 0, 60, -135])
    for f in (0, 3, 7):
        fr = frame(c, f); s = SA.solve(C, fr, phi, roll)
        assert np.allclose(np.linalg.norm(s["E"] - s["S"], axis=1), 0.3) and np.allclose(np.linalg.norm(s["W"] - s["E"], axis=1), 0.3)
        assert np.allclose(s["W"] + s["H3"] @ C["grip_t"], fr["Gt"])                       # the grip point stays
        assert np.allclose((s["H3"] @ C["grip3"])[:, :, 2], fr["G3"][:, 2])                # so does the blade direction
        assert np.allclose(s["Bu"][:, :, 1], SA.unit(s["E"] - s["S"]))                     # upper arm points at the elbow
        Bf, pr, wt, wb = SA.forearm(C, s, np.array([0.0, 35.0]))
        assert np.allclose(Bf[:, 1, :, 1], SA.unit(s["W"] - s["E"]))                       # forearm at the wrist, whatever its roll
        assert np.allclose(pr[:, 1] - pr[:, 0], 35)
        assert np.allclose(s["short"], 0) and np.allclose(np.linalg.det(s["Bu"]), 1)
    s = SA.solve(C, frame(c, 0), [0.0, 180.0], [0.0, 0.0])
    assert s["E"][0, 2] < s["E"][1, 2]                                                     # swivel 0 = elbow down


def test_a_grip_out_of_reach_is_reported_and_the_shoulder_bone_turns_toward_it():
    C, c = consts(), clip(); c["Gt"][0] = c["s0"][0] + [0, -0.75, 0.0]
    far = SA.solve(C, frame(c, 0), 0, 0); near = SA.solve(C, frame(c, 0, turn=10.0), 0, 0)
    assert far["short"][0] > 0.05 and near["short"][0] < far["short"][0]
    assert np.allclose(np.linalg.norm(near["S"] - c["c0"][0], axis=1), 0.15)               # the joint swings about the bone's head


def test_cheapest_stays_unless_the_step_pays_and_closes_a_loop():
    step = np.array([[0.0, 1.0], [1.0, 0.0]])
    U = np.array([[0.0, 5], [0.4, 0], [0.0, 5]])
    assert SA.cheapest(U, step)[1] == [0, 0, 0]                    # 0.4 is cheaper than two steps
    U[1] = [3.0, 0]
    assert SA.cheapest(U, step)[1] == [0, 1, 0]
    U = np.array([[0.0, 1.5], [9.0, 0], [9.0, 0]])                 # open: start cheap, move over; looped: the way back costs too
    assert SA.cheapest(U, step)[1] == [0, 1, 1] and SA.cheapest_loop(U, step, True)[1] == [1, 1, 1]


def test_plan_keeps_the_weapon_on_its_path_and_the_loop_closed():
    C, c = consts(), clip(); O = SA.plan(c, C, loop=True)
    assert np.allclose(O["W"] + O["Bh"] @ C["grip_t"], c["Gt"], atol=1e-9)
    assert np.allclose((O["Bh"] @ C["grip3"])[:, :, 2], c["G3"][:, :, 2], atol=1e-9)
    assert np.allclose(np.linalg.norm(O["E"] - O["S"], axis=1), 0.3) and np.allclose(np.linalg.norm(O["W"] - O["E"], axis=1), 0.3)
    for k in ("Bu", "Bf", "Bh", "E", "W"): assert np.allclose(O[k][0], O[k][-1]), k       # last frame = first
    assert np.allclose(O["Bf"][:, :, 1], SA.unit(O["W"] - O["E"])) and not O["short"].any() and not O["turn"].any()
    assert np.abs(np.diff(O["swivel"])).max() <= 30 and O["cut"].any() and not O["cut"].all()
    m = SA.measure(C, O["Bs"], O["Bu"], O["Bf"], O["Bh"], O["S"], O["E"], O["W"], c["head"])
    assert m["elbow_above_cm"].max() < 5 and not m["hand_high"].any()                      # a low grip: the elbow hangs
    open_ = SA.plan(c, C, loop=False)
    assert np.allclose(open_["W"] + open_["Bh"] @ C["grip_t"], c["Gt"], atol=1e-9)


def test_path_edit_moves_the_grip_toward_the_head_and_tilts_the_blade():
    c = clip(); G3, Gt = SA.edit_path(c["G3"], c["Gt"], c["s0"], c["head"], [{"frames": {3: 1, "4": 0.5}, "move_cm": 10}])
    d = Gt - c["Gt"]; assert np.allclose(np.linalg.norm(d, axis=1)[[3, 4]], [0.10, 0.05]) and np.allclose(np.delete(d, [3, 4], 0), 0)
    goal = c["s0"][3] + (c["head"][3] - c["s0"][3]) * 0.5
    assert np.allclose(np.cross(d[3], goal - c["Gt"][3]), 0, atol=1e-12) and d[3] @ (goal - c["Gt"][3]) > 0 and np.allclose(G3, c["G3"])
    G3, Gt = SA.edit_path(c["G3"], c["Gt"], c["s0"], c["head"], [{"frames": {"2": 1, "5": 0.5}, "tilt_deg": 40, "tilt_toward": [1, 0, 0]}])
    turned = np.degrees(np.arccos(np.clip(np.sum(G3[:, :, 2] * c["G3"][:, :, 2], 1), -1, 1)))
    assert np.allclose(turned[[2, 5]], [40, 20]) and np.allclose(np.delete(turned, [2, 5]), 0, atol=1e-5) and np.allclose(Gt, c["Gt"])
    assert abs(G3[2][:, 2] @ [1, 0, 0] - np.sin(np.radians(40))) < 1e-9                    # toward the direction named
    try: SA.edit_path(c["G3"], c["Gt"], c["s0"], c["head"], [{"frames": {"40": 1}, "move_cm": 5}]); raise AssertionError("accepted")
    except ValueError as e: assert "frame 40" in str(e)


def test_over_targets_and_the_report_line():
    m = {"upper_arm_twist": np.array([10.0, -50, 0]), "forearm_roll": np.array([0.0, 0, 85]), "wrist_twist": np.zeros(3), "wrist_bend": np.zeros(3),
         "swivel": np.zeros(3), "elbow_above_cm": np.array([8.0, 8, 2]), "hand_high": np.array([True, False, False])}
    assert SA.over_targets(m, SA.TARGETS) == [[], ["upper_arm_twist", "elbow_above_cm"], ["forearm_roll"]]   # a raised hand excuses the elbow
    v = lambda t, e: {"upper_arm_twist": t, "forearm_roll": 20, "wrist_twist": 10, "wrist_bend": 30, "elbow_above_cm": e}   # noqa: E731
    rows = [{"frame": 0, "before": v(-132, 19), "after": v(40, 2), "over": [], "grip_off_cm": 0.0, "blade_off_deg": 0.0, "short_cm": 0.0},
            {"frame": 1, "before": v(20, -5), "after": v(-56, 6), "over": ["upper_arm_twist"], "grip_off_cm": 0.1, "blade_off_deg": 0.02, "short_cm": 0.0}]
    s = SA.summary(rows)
    assert s["max"]["before"]["upper_arm_twist"] == 132 and s["max"]["after"]["upper_arm_twist"] == 56 and s["over_targets"] == [1]
    assert s["elbow_above_cm"] == {"before": 19, "after": 6} and s["out_of_reach"] == []
    assert s["line"].startswith("arm solved again under the weapon path: upper arm twist 132 -> 56, forearm roll 20 -> 20")
    assert s["line"].endswith("over a comfort target on 1 of 2 frames; weapon off its path up to 0.1 cm / 0.0 deg")
    rows[1]["short_cm"] = 1.5
    assert SA.summary(rows)["line"].endswith(", out of reach on 1 frames")


def test_a_motion_file_names_one_recipe_or_a_list_in_order():
    M = json.load(open(EXAMPLE, encoding="utf-8"))
    assert schema_check.problems(M, "motion") == []
    assert [e["name"] for e in recipe_list.entries(M)] == ["swing_arm", "one_hand_weapon"]
    assert recipe_list.entry(M, "one_hand_weapon")["weapon"] == "sword.glb" and recipe_list.problems(M) == []
    one = dict(M, recipe=M["recipe"][1])
    assert schema_check.problems(one, "motion") == [] and recipe_list.entries(one) == [M["recipe"][1]]
    assert recipe_list.entries({"action": "idle"}) == []
    twice = dict(M, recipe=[M["recipe"][1], M["recipe"][1]])
    assert recipe_list.problems(twice) == ["recipe one_hand_weapon is listed 2 times: once per action"]
    try: recipe_list.entry(twice, "one_hand_weapon"); raise AssertionError("accepted")
    except ValueError: pass


def test_problems_in_a_list_are_named_by_entry():
    M = json.load(open(EXAMPLE, encoding="utf-8"))
    M["recipe"][0]["name"] = "two_swords"; del M["recipe"][1]["in_hand"]
    p = schema_check.problems(M, "motion")
    assert any(x.startswith("$.recipe[0].name") and "swing_arm" in x for x in p) and any(x.startswith("$.recipe[1]") and "'in_hand'" in x for x in p)
    M = json.load(open(EXAMPLE, encoding="utf-8")); sw = M["recipe"][0]
    del sw["tip"]; sw["path_edits"] = [{"frames": {"12": 2, "x": 1}, "move": 20}]; sw["targets"] = {"elbow": 5}; sw["weights"] = {"edges": 1}
    p = "\n".join(schema_check.problems(M, "motion"))
    for bit in ("'tip' is a required property", "$.recipe[0].path_edits[0].frames", "$.recipe[0].path_edits[0]: Additional properties",
                "$.recipe[0].targets", "$.recipe[0].weights"): assert bit in p, (bit, p)
    assert schema_check.problems(dict(M, recipe=[]), "motion") and schema_check.problems(dict(M, recipe="swing_arm"), "motion")


def test_chain_runs_each_recipe_on_the_file_before_it():
    import chain
    rs = [{"name": "swing_arm"}, {"name": "one_hand_weapon"}]
    assert [d for _, d in chain.recipe_steps(rs, "w/prop_s0.glb")] == ["w/prop_s0_1_swing_arm.glb", "w/prop_s0.glb"]
    assert chain.recipe_steps(rs[:1], "w/prop_s0.glb") == [(rs[0], "w/prop_s0.glb")]
    assert chain.run_recipes(rs, "w/merged_s0.glb", "m.json", "w/prop_s0.glb", run=False) == ["w/prop_s0_1_swing_arm_recipe.json", "w/prop_s0_recipe.json"]


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_"): f(); print("ok", n)
