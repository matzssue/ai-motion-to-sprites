"""server/json_edit.py and server/verdicts.py: what a verdict writes, and that nothing else changes."""
import json
import os

import pytest

from server import json_edit, trail, verdicts
from server.models import VerdictRequest
from server.status import derive

MOTION_OK = VerdictRequest(gate="motion", action="attack", decision="approve")


# json_edit ------------------------------------------------------------------------------------------------------------

def test_insert_into_a_multiline_object_keeps_every_other_byte():
    text = '{\n "_c": "ż comment",\n "a": {\n  "x": 1,\n  "_y": "keep"\n },\n "b": [1, 2]\n}\n'
    out = json_edit.set_member(text, ["a"], "z", {"k": "v", "n": 1.5})
    assert out == '{\n "_c": "ż comment",\n "a": {\n  "x": 1,\n  "_y": "keep",\n  "z": {\n   "k": "v",\n   "n": 1.5\n  }\n },\n "b": [1, 2]\n}\n'


def test_insert_into_a_one_line_object_stays_on_one_line():
    text = '{\n  "a": {"x": 1, "y": [1, {"q": 2}]},\n  "b": 2\n}'
    assert json_edit.set_member(text, ["a"], "z", {"k": 1}) == '{\n  "a": {"x": 1, "y": [1, {"q": 2}], "z": {"k": 1}},\n  "b": 2\n}'


def test_replace_keeps_position_crlf_and_tabs():
    text = '{\r\n\t"a": {\r\n\t\t"z": {"old": true},\r\n\t\t"w": "\\"quoted\\" }"\r\n\t}\r\n}'
    out = json_edit.set_member(text, ["a"], "z", {"new": 1})
    assert out == '{\r\n\t"a": {\r\n\t\t"z": {\r\n\t\t\t"new": 1\r\n\t\t},\r\n\t\t"w": "\\"quoted\\" }"\r\n\t}\r\n}'


def test_empty_object_and_missing_path():
    assert json.loads(json_edit.set_member('{"a": {}}', ["a"], "z", 1)) == {"a": {"z": 1}}
    with pytest.raises(KeyError): json_edit.set_member('{"a": {}}', ["b"], "z", 1)
    with pytest.raises(ValueError): json_edit.set_member('{"a": [1]}', ["a"], "z", 1)


# motion verdict ---------------------------------------------------------------------------------------------------------

def test_approve_motion_writes_only_the_approved_member(ws):
    ws.build("choice"); before = ws.text()
    plan = verdicts.preview(ws.cfg, "tester", MOTION_OK)
    assert ws.text() == before   # a preview writes nothing
    ch = plan.changes[0]
    assert ch.json_path == "$.actions.attack.approved" and ch.before is None
    assert ch.after["score"] == 6.21 and ch.after["bvh"].endswith("attack/kf/kf_s1.bvh") and "\\" not in ch.after["bvh"]
    assert list(ch.after) == ["bvh", "score", "date"]   # exactly what character.py's STOP message asks for
    res = verdicts.apply(ws.cfg, "tester", MOTION_OK.model_copy(update={"expected_config_sha": plan.config_sha}), "me")
    after = ws.text()
    i = before.index('"loop": false') + len('"loop": false')
    assert after[:i] == before[:i] and after.endswith(before[i:])   # only an insertion after the action's last member
    assert after[i:].startswith(',\n   "approved": {\n    "bvh": ')   # in the action's indentation (1 space per level)
    assert list(json.loads(after)) == list(json.loads(before))   # key order of the whole file
    assert json.loads(after)["actions"]["attack"]["_note"] == "keep me"
    st = derive(ws.cfg, "tester")
    assert next(a for a in st.actions if a.name == "attack").step == "approved"
    assert [e.id for e in trail.read(ws.work)] == [res.entry.id] and res.entry.reviewer == "me" and res.entry.changes[0].diff


def test_stale_preview_is_refused(ws):
    ws.build("choice")
    plan = verdicts.preview(ws.cfg, "tester", MOTION_OK)
    ws.write("character.json", ws.text().replace("synthetic character", "synthetic  character"), base=ws.dir)
    with pytest.raises(verdicts.VerdictError) as e:
        verdicts.apply(ws.cfg, "tester", MOTION_OK.model_copy(update={"expected_config_sha": plan.config_sha}), "me")
    assert e.value.status == 409


def test_schema_refusal_leaves_the_file_alone(ws):
    ws.build("choice")
    p = os.path.join(ws.work, "attack", "choice.json"); ch = json.load(open(p)); ch["score"] = "6.21"; ws.write("attack/choice.json", ch)
    before = ws.text()
    with pytest.raises(verdicts.VerdictError) as e: verdicts.apply(ws.cfg, "tester", MOTION_OK, "me")
    assert e.value.status == 422 and "approved.score" in json.dumps(e.value.detail) and ws.text() == before
    assert trail.read(ws.work) == []


def test_failed_replace_keeps_the_old_file_and_no_temp(ws, monkeypatch):
    ws.build("choice"); before = ws.text()

    def boom(src, dst): raise OSError("disk full")
    monkeypatch.setattr(verdicts.os, "replace", boom)
    with pytest.raises(OSError): verdicts.apply(ws.cfg, "tester", MOTION_OK, "me")
    assert ws.text() == before and sorted(os.listdir(ws.dir)) == ["attack.json", "character.json", "model.glb", "rig.json", "walk.fbx", "work"]
    assert trail.read(ws.work) == []


def test_reject_writes_only_the_trail(ws):
    ws.build("choice"); before = ws.text(); mtime = os.path.getmtime(ws.cfg)
    with pytest.raises(verdicts.VerdictError) as e:
        verdicts.apply(ws.cfg, "tester", VerdictRequest(gate="motion", action="attack", decision="reject"), "me")
    assert e.value.status == 422   # a rejection needs a note
    res = verdicts.apply(ws.cfg, "tester", VerdictRequest(gate="motion", action="attack", decision="reject", note="elbow pops"), "me")
    assert ws.text() == before and os.path.getmtime(ws.cfg) == mtime and res.entry.changes == []
    assert [(e.decision, e.note) for e in verdicts.history(ws.cfg, "attack")] == [("reject", "elbow pops")]


def test_verdict_must_match_a_waiting_gate(ws):
    ws.build("poses")
    with pytest.raises(verdicts.VerdictError) as e: verdicts.preview(ws.cfg, "tester", MOTION_OK)
    assert e.value.status == 409
    with pytest.raises(verdicts.VerdictError) as e:
        verdicts.preview(ws.cfg, "tester", VerdictRequest(gate="poses", action="nope", decision="approve"))
    assert e.value.status == 404


# poses and rig verdicts -----------------------------------------------------------------------------------------------

def test_approve_poses_writes_poses_approved(ws):
    ws.build("poses")
    req = VerdictRequest(gate="poses", action="attack", decision="approve", poses_glb="poses_v2/poses.glb")
    verdicts.apply(ws.cfg, "tester", req, "me")
    data = json.load(open(os.path.join(ws.work, "attack", "poses_approved.json"), encoding="utf-8"))
    assert data["glb"] == os.path.join(ws.work, "attack", "poses_v2", "poses.glb").replace("\\", "/")
    assert next(a for a in derive(ws.cfg, "tester").actions if a.name == "attack").step == "motion"


def test_poses_glb_must_be_one_of_the_options(ws):
    ws.build("poses")
    for bad in ("../../rig.json", "poses/../../../secret.glb", "C:/x/poses.glb"):
        with pytest.raises(verdicts.VerdictError) as e:
            verdicts.preview(ws.cfg, "tester", VerdictRequest(gate="poses", action="attack", decision="approve", poses_glb=bad))
        assert e.value.status == 422


def test_rig_approval_is_trail_only(ws):
    ws.build("rig_ai"); before = ws.text()
    plan = verdicts.preview(ws.cfg, "tester", VerdictRequest(gate="rig", decision="approve"))
    assert plan.changes == []
    verdicts.apply(ws.cfg, "tester", VerdictRequest(gate="rig", decision="approve"), "me")
    assert ws.text() == before and len(trail.read(ws.work)) == 1
