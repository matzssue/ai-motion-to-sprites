"""server/status.py: the pipeline state read from files by the rules of character.py."""
import json
import os
from datetime import datetime, timezone

from server import status, trail
from server.models import TrailEntry


def stages(ws):
    st = status.derive(ws.cfg, "tester")
    return {s.name: s.status for s in st.stages}, st


def test_fresh_character(ws):
    s, st = stages(ws)
    assert s == {"prepare": "stale", "rig": "stale", "rig_ai": "stale", "calibration": "blocked", "ai": "blocked",
                 "merge": "blocked", "preview": "blocked"}
    assert st.character.gate is None and st.character.stale_stage == "prepare" and not st.character.done
    assert "no in.fbx yet" in st.stages[0].detail


def test_new_ai_rig_waits_for_review(ws):
    ws.build("rig_ai")
    s, st = stages(ws)
    assert s["rig_ai"] == "waiting" and s["calibration"] == "blocked"
    assert st.character.gate.kind == "rig" and [i.label for i in st.character.gate.images] == ["rig_ai_preview_side.png"]


def test_rig_approval_in_the_trail_passes_the_gate(ws):
    ws.build("rig_ai")
    at = datetime.fromtimestamp(ws.t + 60, timezone.utc).isoformat(timespec="seconds")   # the test files are dated in the future
    trail.append(ws.work, TrailEntry(id="1", at=at, reviewer="r", gate="rig", decision="approve"))
    s, st = stages(ws)
    assert s["rig_ai"] == "up_to_date" and s["calibration"] == "stale" and st.character.gate is None


def test_a_later_output_passes_the_rig_gate(ws):
    ws.build("calibration")
    s, _ = stages(ws)
    assert s["rig_ai"] == "up_to_date" and s["calibration"] == "up_to_date" and s["ai"] == "stale" and s["merge"] == "blocked"


def test_rig_config_edit_makes_rig_ai_stale_and_blocks_the_rest(ws):
    ws.build("choice")
    ws.touch(os.path.join(ws.dir, "rig.json"))
    s, st = stages(ws)
    assert s["rig_ai"] == "stale" and "rig.json newer than rig_ai.glb" in st.stages[2].detail
    assert s["calibration"] == s["ai"] == s["merge"] == "blocked"


def test_key_poses_wait_with_their_options(ws):
    ws.build("poses")
    s, st = stages(ws)
    a = next(x for x in st.actions if x.name == "attack")
    assert s["ai"] == "waiting" and a.step == "poses" and a.status == "waiting"
    assert st.character.gate.kind == "poses" and st.character.gate.action == "attack"
    assert a.gate.poses_options == ["poses/poses.glb", "poses_v2/poses.glb"]
    assert "frames 0, 12" in a.gate.needs and [i.label for i in a.gate.images] == ["attack/poses/preview/attack.png"]


def test_body_without_poses_runs_and_stops(ws):
    ws.build("body")
    s, st = stages(ws)
    assert s["ai"] == "stale" and s["merge"] == "blocked"


def test_motion_waits_for_the_verdict(ws):
    ws.build("choice")
    s, st = stages(ws)
    a = next(x for x in st.actions if x.name == "attack")
    assert s["ai"] == "waiting" and a.step == "motion" and st.character.gate.kind == "motion"
    assert a.best.name == "kf_s1" and a.best.score == 6.21 and [x.score for x in a.samples] == [14.2, 6.21]
    assert a.audit.result == "FAIL" and a.review_sources == ["choice"]


def test_approved_motion_moves_on_to_merge(ws):
    ws.build("approve")
    s, st = stages(ws)
    a = next(x for x in st.actions if x.name == "attack")
    assert s["ai"] == "up_to_date" and a.step == "approved" and a.approved.score == 6.21 and s["merge"] == "stale"


def test_everything_done(ws):
    ws.build("preview")
    s, st = stages(ws)
    assert set(s.values()) == {"up_to_date"} and st.character.done
    a = next(x for x in st.actions if x.name == "attack")
    assert a.merged_audit.result == "FAIL" and a.review_sources == ["choice", "merged"]


def test_merge_audit_fail_beyond_the_approved_score(ws):
    ws.build("approve"); ws.write("tester_with_prop.glb")
    ws.write("report.json", {"walk": {"result": "OK", "score": 0}, "attack": {"result": "FAIL", "score": 6.21 + 0.5}})
    s, st = stages(ws)
    assert s["merge"] == "failed" and "attack 6.71" in st.stages[5].detail and s["preview"] == "blocked"
    ws.write("report.json", {"walk": {"result": "OK", "score": 0}, "attack": {"result": "FAIL", "score": 6.30}})   # within NOISE
    assert stages(ws)[0]["merge"] == "stale"


def test_calibration_fail(ws):
    ws.build("rig_ai"); ws.audit("calibration_walk", "FAIL", 2.0)
    s, st = stages(ws)
    assert s["calibration"] == "failed" and "walk" in st.stages[3].detail


def test_missing_key_poses_is_an_error(ws):
    ws.build("calibration")
    ws.write("attack.json", json.dumps({"action": "attack", "phases": [{"duration": 1, "text": "x"}]}), base=ws.dir)
    s, st = stages(ws)
    assert s["ai"] == "failed" and "key_poses" in st.stages[4].detail


def test_first_ai_action_in_order_decides_the_stage(ws):
    ws.build("choice")
    C = json.loads(ws.text()); C["actions"]["jump"] = {"ai": "jump.json"}
    ws.write("character.json", json.dumps(C), base=ws.dir)
    ws.write("jump.json", json.dumps({"action": "jump", "phases": [{"duration": 1, "text": "x"}], "key_poses": {"a": 0}}), base=ws.dir)
    s, st = stages(ws)
    assert s["ai"] == "waiting" and st.character.gate.action == "attack"
    assert next(x for x in st.actions if x.name == "jump").status == "stale"


def test_invalid_config_names_the_problem(ws):
    ws.write("character.json", json.dumps({"name": "tester"}), base=ws.dir)
    s, st = stages(ws)
    assert set(s.values()) == {"blocked"} and "does not match" in st.character.problems[0]
