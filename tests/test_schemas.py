"""Configs against schemas/: every file in examples/ validates, broken configs are named by JSON path.
AMTS_EXTRA_CONFIGS="<dir>/*/character.json;..." also checks real characters (their rig config and motion files too).
python -m pytest tests  (or: python tests/test_schemas.py)"""
import glob, json, os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "pipeline", "lib"))
import schema_check

EXAMPLES = os.path.join(ROOT, "examples")


def kind(path):
    b = os.path.basename(path)
    return "character" if b.startswith("character") else "rig" if b.startswith("rig") else "motion"


def test_every_example_validates():
    files = sorted(glob.glob(os.path.join(EXAMPLES, "*.json")))
    assert files
    for f in files:
        assert schema_check.problems(json.load(open(f, encoding="utf-8")), kind(f)) == [], f


def test_example_character_with_its_files():
    C = schema_check.load_character(os.path.join(EXAMPLES, "character.example.json"))
    assert C["name"] == "crossbowman"


def test_extra_configs():
    pats = [p for p in os.environ.get("AMTS_EXTRA_CONFIGS", "").split(";") if p]
    for f in sorted(x for p in pats for x in glob.glob(p)):
        if kind(f) == "character": schema_check.load_character(f)
        else: assert schema_check.problems(json.load(open(f, encoding="utf-8")), kind(f)) == [], f


def test_missing_grip_keys_are_named():
    M = json.load(open(os.path.join(EXAMPLES, "motion.example.json"), encoding="utf-8"))
    del M["grip"]["elbow_deg"]; del M["grip"]["right"]["palm"]
    p = schema_check.problems(M, "motion")
    assert any(x.startswith("$.grip: 'elbow_deg' is a required property") for x in p)
    assert any(x.startswith("$.grip.right: give the palm side") for x in p)


def test_required_by_caller():
    p = schema_check.problems({"action": "walk"}, "motion", ("phases", "grip"))
    assert sorted(p) == ["$: 'grip' is a required property", "$: 'phases' is a required property"]


def test_bad_words_and_actions():
    M = json.load(open(os.path.join(EXAMPLES, "motion.example.json"), encoding="utf-8"))
    M["grip"]["left"]["fingers"] = "sideways"; M["key_poses"]["aim"] = "44"
    p = schema_check.problems(M, "motion")
    assert any(x.startswith("$.grip.left.fingers:") for x in p) and any(x.startswith("$.key_poses.aim:") for x in p)
    C = json.load(open(os.path.join(EXAMPLES, "character.example.json"), encoding="utf-8"))
    C["actions"]["_note"] = "x"; C["actions"]["attack"]["approved"] = {"score": 1.4}; del C["rig_config"]
    p = schema_check.problems(C, "character")
    assert "$.actions._note: 'x' is not of type 'object'" in p
    assert "$.actions.attack.approved: 'bvh' is a required property" in p
    assert "$: 'rig_config' is a required property" in p


def test_load_names_file():
    import tempfile
    d = tempfile.mkdtemp(); f = os.path.join(d, "rig.json")
    json.dump({"prop": {"name": "bow"}}, open(f, "w"))
    try: schema_check.load(f, "rig"); assert False
    except SystemExit as e: assert f in str(e) and "$: 'joints' is a required property" in str(e) and "$.prop:" in str(e)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
