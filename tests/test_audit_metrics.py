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
