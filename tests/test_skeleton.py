"""Skeleton profiles (no Blender): loader vs schema, role lookup on a synthetic rig, skipped metrics, the Mixamo default.
python -m pytest tests  (or: python tests/test_skeleton.py)"""
import copy, json, os, sys
import pytest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "pipeline", "lib"))
import audit_metrics, schema_check, skeleton

MIXAMO = json.load(open(os.path.join(ROOT, "skeletons", "mixamo.json"), encoding="utf-8"))


def both(D):
    """(loader problems, schema problems) of one profile."""
    return skeleton.problems(D), schema_check.problems(D, "skeleton")


def test_builtin_profiles_valid():
    for f in os.listdir(os.path.join(ROOT, "skeletons")):
        D = json.load(open(os.path.join(ROOT, "skeletons", f), encoding="utf-8"))
        assert both(D) == ([], []), f
        assert skeleton.load(f[:-5]).name == f[:-5]


def test_role_lists_match_schema():
    S = schema_check.schema("skeleton")
    assert set(S["$defs"]["side"]["properties"]) == set(skeleton.SIDED) | {"finger_chains"}
    assert set(S["$defs"]["side"]["properties"]["finger_chains"]["properties"]) == set(skeleton.FINGERS)
    assert set(S["properties"]["bones"]["properties"]) == set(skeleton.CENTER) | {"left", "right"}
    assert set(S["properties"]["absent"]["items"]["enum"]) == {r for r, req in {**skeleton.CENTER, **skeleton.SIDED}.items() if not req}
    assert set(S["$defs"]["side"]["required"]) == {r for r, req in skeleton.SIDED.items() if req}
    assert set(S["properties"]["regions"]["required"]) == set(skeleton.REGIONS)


def test_missing_required_role_named_with_file(tmp_path):
    D = copy.deepcopy(MIXAMO); del D["bones"]["left"]["hand"]
    lo, sc = both(D)
    assert "bones.left.hand: missing (required)" in lo and any(p.startswith("$.bones.left: 'hand' is a required") for p in sc)
    p = tmp_path / "bad.json"; p.write_text(json.dumps(D))
    with pytest.raises(skeleton.ProfileError, match=r"(?s)bad\.json.*bones\.left\.hand: missing"):
        skeleton.load(str(p))
    with pytest.raises(SystemExit, match="bad.json"):
        schema_check.load_skeleton(str(p))


def test_unknown_role():
    D = copy.deepcopy(MIXAMO); D["bones"]["left"]["claw"] = "LeftClaw"; D["bones"]["tail"] = "Tail"; D["absent"] = ["wings"]
    lo, sc = both(D)
    assert any(x.startswith("bones.left.claw: unknown role") for x in lo) and any(x.startswith("bones.tail: unknown role") for x in lo)
    assert "absent: unknown role 'wings'" in lo
    assert "$.bones.left: unknown role (per side: shoulder, upper_arm, forearm, hand, fingers, upper_leg, lower_leg, foot, toe, toe_end; or finger_chains)" in sc
    assert any(x.startswith("$.bones: unknown role") for x in sc) and any(x.startswith("$.absent[0]") for x in sc)


def test_optional_part_absent():
    D = copy.deepcopy(MIXAMO)
    for s in ("left", "right"): del D["bones"][s]["fingers"]; del D["bones"][s]["toe_end"]
    lo, sc = both(D)
    assert lo and sc   # neither named nor declared absent: an error, not a silent "no fingers"
    D["absent"] = ["fingers", "toe_end"]
    assert both(D) == ([], [])
    P = skeleton.Profile(D)
    assert not P.has("fingers") and not P.has("fingers", "L") and P.has("toe", "R")
    sk = P.skipped(audit_metrics.NEEDS)
    assert set(sk) == {"fingers_in_prop", "fingers_in_head", "finger_jump", "loose_fingers", "finger_tip_gap", "finger_tip_fold", "finger_curl_L", "finger_curl_R",
                       "wrist_flexion_L", "wrist_flexion_R", "wrist_deviation_L", "wrist_deviation_R"} and "has no fingers" in sk["finger_jump"]
    with pytest.raises(skeleton.ProfileError, match="has no fingers.left"):
        P.bone("fingers", "Left")
    D["absent"] = ["hand"]
    assert "absent: hand is required and cannot be absent" in skeleton.problems(D)


def test_region_without_bones_skips_its_metrics():
    P = skeleton.load().without(["shoulder"])
    assert P.region_bones("clavicles") == []
    assert set(P.skipped(audit_metrics.NEEDS)) == {"prop_in_clavicles", "skin_tear"}   # the clavicle is a shoulder role


# a small synthetic rig: prefix "x:", two spine bones, fingers on the left only as grown finger_* bones, a prop on the chest
PARENTS = {"x:root": None, "x:spine_a": "x:root", "x:spine_b": "x:spine_a", "x:neck": "x:spine_b", "x:head": "x:neck",
           "prop": "x:spine_b"}
for s, o in (("l", "Left"), ("r", "Right")):
    PARENTS.update({"x:clav_" + s: "x:spine_b", "x:arm_" + s: "x:clav_" + s, "x:fore_" + s: "x:arm_" + s, "x:hand_" + s: "x:fore_" + s,
                    "x:mid1_" + s: "x:hand_" + s, "x:mid2_" + s: "x:mid1_" + s,
                    "x:thigh_" + s: "x:root", "x:shin_" + s: "x:thigh_" + s, "x:foot_" + s: "x:shin_" + s})
PARENTS.update({"finger_L0_1": "x:hand_l", "finger_L0_2": "finger_L0_1", "x:sword": "x:hand_r"})
SYN = {"name": "syn", "prefix": "x:", "absent": ["head_end", "toe", "toe_end"],
       "bones": {"hips": "root", "spine": ["spine_a", "spine_b"], "neck": "neck", "head": "head"},
       "regions": {"head": ["head", "neck", "head_end"], "torso": ["spine", "hips"], "clavicles": ["shoulder"], "legs": ["upper_leg", "lower_leg"]}}
for s in ("l", "r"):
    SYN["bones"]["left" if s == "l" else "right"] = {"shoulder": "clav_" + s, "upper_arm": "arm_" + s, "forearm": "fore_" + s,
                                                     "hand": "hand_" + s, "fingers": "mid1_" + s, "upper_leg": "thigh_" + s,
                                                     "lower_leg": "shin_" + s, "foot": "foot_" + s}


def test_role_lookup_on_synthetic_rig():
    P = skeleton.Profile(SYN)
    assert both(SYN) == ([], [])
    R = P.bind(PARENTS, exclude=("x:sword",))
    assert P.bone("hand", "L") == "x:hand_l" and P.spine == ["x:spine_a", "x:spine_b"]
    assert sorted(P.region_bones("torso")) == ["x:root", "x:spine_a", "x:spine_b"] and P.region_bones("head") == ["x:head", "x:neck"]
    assert R.fingers == {"x:mid1_l", "x:mid2_l", "finger_L0_1", "finger_L0_2", "x:mid1_r", "x:mid2_r"}   # the excluded prop is no finger
    assert R.finger_root["finger_L0_2"] == "finger_L0_1" and R.finger_root["x:mid2_r"] == "x:mid1_r"
    assert [R.bone_side(b) for b in ("finger_L0_2", "x:shin_r", "x:clav_l", "x:spine_b", "prop", "")] == ["L", "R", "L", "", "", ""]
    assert R.arms == {"x:arm_l", "x:fore_l", "x:hand_l", "x:arm_r", "x:fore_r", "x:hand_r"}
    assert P.aim("x:root") == "x:spine_a" and P.aim("x:spine_b") == "x:neck" and P.aim("x:head") is None and P.aim("x:foot_l") is None
    assert P.skipped(audit_metrics.NEEDS) == {}


def test_profile_must_match_rig():
    P = skeleton.Profile(SYN)
    rig = dict(PARENTS); del rig["x:fore_r"]; rig["x:hand_r"] = "x:arm_r"
    with pytest.raises(skeleton.ProfileError, match=r"skeleton 'syn'.*forearm\.right -> 'x:fore_r'"):
        P.bind(rig)


def test_skipped_metric_does_not_score():
    rows = [{"t": 0.0, "hands_in_head": 0.002, "finger_jump": 40.0, "_where": {}, "_side": {}},
            {"t": 0.25, "hands_in_head": 0.009, "finger_jump": 50.0, "_where": {}, "_side": {}}]
    lim = {"hands_in_head": 0.005, "finger_jump": 6}
    group = {k: v[2] for k, v in audit_metrics.METRICS.items()}
    full = audit_metrics.judge(rows, lim, group)
    skip = skeleton.load().without(["fingers"]).skipped(audit_metrics.NEEDS)
    errors, scores, score, _ = audit_metrics.judge(rows, {k: v for k, v in lim.items() if k not in skip}, group)
    assert "finger_jump" in full[0] and full[2] == 8.13
    assert set(errors) == {"hands_in_head"} and score == 0.8 and scores == {"penetration": 0.8}


def test_default_is_mixamo_and_old_retarget_map():
    P = skeleton.load()
    assert P.name == "mixamo" and P.prefix == "mixamorig:"
    old = {"Hips": "Hips", "Spine1": "Spine", "Spine2": "Spine1", "Chest": "Spine2", "Neck1": "Neck", "Head": "Head"}
    for s in ("Left", "Right"):
        old.update({s + "Shoulder": s + "Shoulder", s + "Arm": s + "Arm", s + "ForeArm": s + "ForeArm", s + "Hand": s + "Hand",
                    s + "Leg": s + "UpLeg", s + "Shin": s + "Leg", s + "Foot": s + "Foot", s + "ToeBase": s + "ToeBase"})
    pairs = skeleton.load("soma").pairs(P)
    assert [(a, P.short(b)) for a, b in pairs] == list(old.items())   # same bones, same order as the literal it replaced
    assert {P.short(b): P.short(P.aim(b) or "") for _, b in pairs} == {
        "Hips": "Spine", "Spine": "Spine1", "Spine1": "Spine2", "Spine2": "Neck", "Neck": "Head", "Head": "HeadTop_End",
        **{s + k: s + v for s in ("Left", "Right") for k, v in (("Shoulder", "Arm"), ("Arm", "ForeArm"), ("ForeArm", "Hand"),
                                                                 ("Hand", "HandMiddle1"), ("UpLeg", "Leg"), ("Leg", "Foot"),
                                                                 ("Foot", "ToeBase"), ("ToeBase", "Toe_End"))}}


def test_same_roles_cover_tips_and_fingers():
    M = dict(skeleton.load().same_roles(skeleton.load("soma")))
    assert len(M) == 4 + 3 + 2 * 10 and M["mixamorig:LeftUpLeg"] == "LeftLeg" and M["mixamorig:LeftLeg"] == "LeftShin"
    assert M["mixamorig:HeadTop_End"] == "HeadEnd" and M["mixamorig:RightToe_End"] == "RightToeEnd"


def mixamo_rig(fingers=True):
    P = skeleton.load(); par = {}
    chain = [P.bone("hips")] + P.spine + [P.bone("neck"), P.bone("head"), P.bone("head_end")]
    for a, b in zip([None] + chain, chain): par[b] = a
    for s in skeleton.SIDES:
        prev = P.spine[-1]
        for r in ("shoulder", "upper_arm", "forearm", "hand") + (("fingers",) if fingers else ()):
            par[P.bone(r, s)] = prev; prev = P.bone(r, s)
        prev = P.bone("hips")
        for r in ("upper_leg", "lower_leg", "foot", "toe", "toe_end"):
            par[P.bone(r, s)] = prev; prev = P.bone(r, s)
    return par


def test_default_fits_old_rigs_explicit_must_match():
    logs = []
    R = skeleton.for_rig(None, mixamo_rig(), log=logs.append)
    assert logs == [] and R.prof.has("fingers") and R.prof.skipped(audit_metrics.NEEDS) == {}
    R = skeleton.for_rig(None, mixamo_rig(fingers=False), log=logs.append)   # a Mixamo rig without finger bones ran before
    assert logs == ["skeleton mixamo: the rig has no fingers bones -> treated as absent"] and not R.prof.has("fingers")
    with pytest.raises(skeleton.ProfileError, match="fingers.left -> 'mixamorig:LeftHandMiddle1'"):
        skeleton.for_rig("mixamo", mixamo_rig(fingers=False))


def test_finger_chains():
    """Optional per-side finger chains: the retarget carries finger bends only where both skeletons list the finger;
    Mixamo lists none (a template's finger bones own no skin), so a Mixamo retarget stays as it was."""
    soma, amts, mix = skeleton.load("soma"), skeleton.load("amts"), skeleton.load()
    assert mix.finger_chains("L") == {} and mix.finger_chains("Right") == {}
    for s in ("Left", "Right"):
        assert set(soma.finger_chains(s)) == set(amts.finger_chains(s)) == set(skeleton.FINGERS)
        assert all(len(c) == 3 for c in amts.finger_chains(s).values()) and len(soma.finger_chains(s)["index"]) == 4
    assert amts.finger_chains("L")["thumb"] == ["thumb.1.L", "thumb.2.L", "thumb.3.L"]
    assert amts.without(["fingers"]).finger_chains("L") == {}
    D = copy.deepcopy(MIXAMO)
    D["bones"]["left"]["finger_chains"] = {"index": ["LeftHandIndex1", "LeftHandIndex2"], "claw": ["a", "b", "c"], "_": "note"}
    D["bones"]["right"]["finger_chains"] = ["RightHandIndex1"]
    lo, sc = both(D)
    assert "bones.left.finger_chains.index: a list of at least 3 bone names" in lo
    assert any(x.startswith("bones.left.finger_chains.claw: unknown finger") for x in lo)
    assert "bones.right.finger_chains: an object {finger: [bones]}" in lo and len(sc) >= 3
    D = copy.deepcopy(MIXAMO); D["bones"]["left"]["finger_chains"] = {"index": ["LeftHandIndex1", "LeftHandIndex2", "LeftHandIndex3"]}
    assert both(D) == ([], [])
    R = skeleton.Profile(D).bind(mixamo_rig() | {"mixamorig:LeftHandIndex1": "mixamorig:LeftHand"})   # no Index2/3 on this rig
    assert R.prof.finger_chains("L") == {} and skeleton.Profile(D).finger_chains("L")["index"][0] == "mixamorig:LeftHandIndex1"
    full = mixamo_rig() | {"mixamorig:LeftHandIndex%d" % i: "x" for i in (1, 2, 3)}
    assert skeleton.Profile(D).bind(full).prof.finger_chains("L") == {"index": ["mixamorig:LeftHandIndex%d" % i for i in (1, 2, 3)]}


def test_locate_and_args(tmp_path):
    with pytest.raises(skeleton.ProfileError, match="built-in: amts, mixamo, soma"):
        skeleton.load("unreal")
    assert skeleton.locate("rig/x.json", str(tmp_path)) == os.path.normpath(os.path.join(str(tmp_path), "rig/x.json"))
    assert skeleton.take_arg(["a.bvh", "--skeleton", "soma", "b.glb"]) == (["a.bvh", "b.glb"], "soma")
    assert skeleton.take_arg(["a", "--skeleton=x.json"]) == (["a"], "x.json") and skeleton.take_arg(["a"]) == (["a"], None)


def test_character_with_skeleton(tmp_path):
    C = json.load(open(os.path.join(ROOT, "examples", "character.example.json"), encoding="utf-8"))
    for k in ("rig_config",): C[k] = os.path.join(ROOT, "examples", C[k])
    C["actions"] = {"walk": {"library": "walk.fbx"}}
    D = copy.deepcopy(SYN); (tmp_path / "rig").mkdir(); (tmp_path / "rig" / "syn.json").write_text(json.dumps(D))
    C["skeleton"] = "rig/syn.json"; (tmp_path / "character.json").write_text(json.dumps(C))
    assert schema_check.load_character(str(tmp_path / "character.json"))["skeleton"] == "rig/syn.json"
    del D["bones"]["neck"]; (tmp_path / "rig" / "syn.json").write_text(json.dumps(D))
    with pytest.raises(SystemExit, match=r"(?s)syn\.json.*bones\.neck: missing \(required\)"):
        schema_check.load_character(str(tmp_path / "character.json"))
    C["skeleton"] = "mixam"; (tmp_path / "character.json").write_text(json.dumps(C))
    with pytest.raises(SystemExit, match="no built-in skeleton profile 'mixam'"):
        schema_check.load_character(str(tmp_path / "character.json"))


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
