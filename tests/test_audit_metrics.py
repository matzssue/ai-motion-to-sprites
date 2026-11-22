"""Metric catalog: every audit metric has a label, a unit the pages know and a group, and the web viewer's copy is current."""
import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "pipeline", "lib"))
import audit_metrics as M  # noqa: E402

GROUPS = {"penetration", "joints", "smoothness", "grip", "feet"}


def test_every_metric_has_label_unit_group_and_needs():
    assert set(M.LABELS) == set(M.METRICS)
    assert set(M.NEEDS) == set(M.METRICS)
    for k, (_, unit, group) in M.METRICS.items():
        assert unit in M.UNIT_SHOWN, k
        assert group in GROUPS, k


def test_web_catalog_is_current():
    path = os.path.join(ROOT, "web", "src", "audit", "catalog.json")
    with open(path, encoding="utf-8") as f:   # text mode: a CRLF checkout reads as LF
        assert f.read() == M.catalog_json(), (
            "web/src/audit/catalog.json is out of date: python pipeline/lib/audit_metrics.py --catalog " + path)


def test_review_page_formats_fractions_as_percent():
    sys.path.insert(0, os.path.join(ROOT, "pipeline", "review"))
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    import review_page
    assert review_page.fmt("skin_tear", 0.143) == "14%"
    assert review_page.fmt("finger_tip_fold", 0.109) == "11%"
    assert review_page.fmt("face_skew", 0.011) == "1.1 cm"
    assert review_page.fmt("wrist_twist_L", 74.2) == "74.2&deg;"
    assert review_page.LABELS["prop_in_pocket"] == "stock in armpit skin"


def test_height_is_the_rest_pose_span():
    rest = [0.02, 0.9, 1.92]          # feet, hips, head top: 1.90 m
    assert abs(M.height(rest) - 1.90) < 1e-9


def test_scaled_moves_only_metre_limits():
    lim = {"hands_in_head": 0.005, "wrist_bend_L": 80.0, "skin_tear": 0.1, "fingers_in_head": None}
    out = M.scaled(lim, 1.90)
    assert abs(out["hands_in_head"] - 0.005 * 1.90 / 1.8) < 1e-12
    assert out["wrist_bend_L"] == 80.0 and out["skin_tear"] == 0.1
    assert "fingers_in_head" not in out          # reported only: no limit to scale


def test_head_direction_against_the_rest_facing():
    f = M.facing([0.2, 0.0, 1.4], [-0.2, 0.01, 1.45])            # left shoulder at +X: the rest pose faces -Y
    assert abs(f[1] + 1) < 0.01 and abs(f[2]) < 1e-12
    f = [0.0, -1.0, 0.0]
    yaw, pitch = M.head_angles([0.5, -0.5, 0.0], f)
    assert abs(yaw - 45) < 1e-9 and abs(pitch) < 1e-9             # + = toward the character's left
    yaw, pitch = M.head_angles([0.0, -2.0, -2.0], f)
    assert abs(yaw) < 1e-9 and abs(pitch - 45) < 1e-9             # + = looking down
    assert abs(M.head_angles([-1.0, 0.0, 0.0], f)[0] + 90) < 1e-9


def test_head_summary_warns_on_a_clip_that_looks_away():
    away = M.head_summary([35, 14, 3, 43, 40, -30], [3, 3, -10, 3, 3, 3])   # the knight's attack straight from Kimodo
    assert away == {"yaw_mean": 27.5, "yaw_max": 43.0, "pitch_mean": 4.2, "pitch_max": 10.0, "warn": True}
    assert M.head_summary([0, 1, 0, -1], [3, 3, 3, 3])["warn"] is False     # head locked forward
    assert M.head_summary([0] * 9 + [60], [0] * 10)["warn"] is False        # one glance is not a clip looking away


def test_arm_limits_sit_between_the_two_verdicts():
    for s in "LR":
        assert 80.2 < M.METRICS["upper_arm_twist_" + s][0] < 132          # accepted clip's left arm; the rejected right arm
        assert 0.063 * 1.8 / 1.9 < M.METRICS["elbow_above_shoulder_" + s][0] < 0.11 * 1.8 / 1.9   # accepted, rejected at the knight's 1.90 m
        assert M.METRICS["forearm_roll_" + s][0] is None                  # accepted clips roll it 85-145 deg
    assert M.METRICS["head_yaw"][0] is None and M.METRICS["head_pitch"][0] is None


def test_a_hand_a_recipe_solved_again_is_not_scored_against_its_key_pose():
    reps = [{"recipe": "swing_arm", "action": "attack", "sets_hand": "R"}, {"recipe": "one_hand_weapon", "action": "attack", "hand": "R"},
            {"recipe": "swing_arm", "action": "block", "sets_hand": "L"}, "not a report"]
    assert M.hands_set_by_recipes(reps, "attack") == {"R"} and M.hands_set_by_recipes([], "attack") == set()
