"""Recipes (pipeline/recipes/): every file has the fixed header, the index is fresh, the schema lists the same names;
the one-handed weapon's rules on synthetic data.
python -m pytest tests  (or: python tests/test_recipes.py)"""
import json, os, sys

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
for d in ("tools", os.path.join("pipeline", "lib"), os.path.join("pipeline", "recipes")):
    sys.path.insert(0, os.path.join(ROOT, d))
import recipes_index as RI
import schema_check
import one_hand_weapon as OHW

EXAMPLE = os.path.join(ROOT, "examples", "one_hand_weapon.example.json")


def test_every_recipe_has_the_header():
    R = RI.recipes()
    assert "one_hand_weapon" in R and "prop_in_hands" in R
    for n, (_, h) in R.items():
        assert all(h[f] for f in RI.FIELDS), n
    assert "EXPERIMENTAL" in R["prop_in_hands"][1]["title"]


def test_index_is_fresh():
    assert open(RI.INDEX, encoding="utf-8").read() == RI.index(), "run python tools/recipes_index.py"
    assert len(RI.index().splitlines()) < 350


def test_header_problems_are_named(tmp_path):
    def problem(doc):
        p = tmp_path / "x.py"; p.write_text('"""%s"""\n' % doc, encoding="utf-8")
        try: RI.header(str(p))
        except ValueError as e: return str(e)
        return None
    good = "Title.\nUse when: a\nNot for: b\n    more of b\nInputs: c\nOutput: d\nChecks: e\n\nusage"
    assert problem(good) is None
    assert "needs, in this order" in problem(good.replace("Not for: b\n    more of b\n", ""))
    assert "needs, in this order" in problem("Title.\nNot for: b\nUse when: a\nInputs: c\nOutput: d\nChecks: e")
    assert "outside a field" in problem("Title.\nstray line\nUse when: a")
    assert "empty header field" in problem(good.replace("Inputs: c", "Inputs:"))


def test_schema_lists_the_recipe_names():
    S = json.load(open(os.path.join(ROOT, "schemas", "motion.schema.json"), encoding="utf-8"))
    assert S["properties"]["recipe"]["properties"]["name"]["enum"] == RI.names()
    assert all(os.path.exists(os.path.join(RI.RECIPES, n + ".py")) for n in RI.names())


def test_unknown_recipe_lists_the_valid_names():
    M = json.load(open(EXAMPLE, encoding="utf-8"))
    assert schema_check.problems(M, "motion") == []
    M["recipe"]["name"] = "two_swords"
    p = schema_check.problems(M, "motion")
    assert len(p) == 1 and p[0].startswith("$.recipe.name") and "one_hand_weapon" in p[0]


def test_missing_recipe_inputs_are_named():
    M = json.load(open(EXAMPLE, encoding="utf-8"))
    del M["recipe"]["in_hand"]; M["recipe"]["grip"] = [[0, 0, 0]]; M["recipe"]["hand"] = "both"
    p = "\n".join(schema_check.problems(M, "motion"))
    assert "'in_hand' is a required property" in p and "$.recipe.grip" in p and "$.recipe.hand" in p


def test_edge_points_fill_long_edges():
    co = [(0, 0, 0), (0, 0, 1.0), (0.01, 0, 0)]
    pts = OHW.edge_points(co, [(0, 1), (0, 2)], step=0.02)
    assert len(pts) == 3 + 49                                   # the 1 m edge in 50 parts, the 1 cm edge untouched
    z = np.sort(pts[:, 2]); assert np.diff(z).max() <= 0.02 + 1e-9
    assert np.allclose(pts[:3], co)


def test_grip_mask_takes_the_section_between_the_ends():
    pts = np.array([(0, 0, z) for z in (-0.2, -0.05, 0.0, 0.05, 0.3)] + [(0.5, 0.5, 0.0)])
    assert OHW.grip_mask(pts, (0, 0, -0.075), (0, 0, 0.075)).tolist() == [False, True, True, True, False, True]
    assert OHW.grip_mask(pts, (0, 0, 0.075), (0, 0, -0.075)).tolist() == [False, True, True, True, False, True]   # either order


def test_summary_counts_frames_and_names_the_worst():
    rows = [{"frame": 0, "in_body_cm": {}, "grip_covered": 0.9}, {"frame": 1, "in_body_cm": {"legs.L": 2.5, "torso": 0.4}, "grip_covered": 0.8},
            {"frame": 2, "in_body_cm": {"torso": 1.0}, "grip_covered": 0.85}]
    s = OHW.summary(rows)
    assert s["frames"] == 3 and s["in_body_frames"] == 2 and s["worst"][0] == [2.5, 1, "legs.L"]
    assert s["grip_covered"] == {"min": 0.8, "mean": 0.85}
    assert s["line"] == "weapon in the body on 2 of 3 frames (worst 2.5 cm on fr. 1, legs.L); the fist covers 80-90% of the grip"
    clean = OHW.summary(rows[:1])
    assert clean["in_body_frames"] == 0 and clean["line"] == "weapon in the body on 0 of 1 frames; the fist covers 90-90% of the grip"


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    for n, f in sorted(globals().items()):
        if n.startswith("test_"):
            f(Path(tempfile.mkdtemp())) if f.__code__.co_argcount else f(); print("ok", n)
