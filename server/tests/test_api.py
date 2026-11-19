"""The HTTP API through FastAPI's test client: state, manifest and file safety, verdicts, runs and their log stream."""
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from conftest import fake_command
from server.app import create_app
from server.settings import Character, Settings, assign_ids, find_configs

ORIGIN = "http://localhost:3000"


def client_for(ws, command=None):
    s = Settings(characters=[Character("tester", ws.cfg)], pipeline_command=command or fake_command(), origins=[ORIGIN], reviewer="tests")
    return TestClient(create_app(s, allowed_hosts=("testserver", "127.0.0.1")))


@pytest.fixture
def api(ws):
    with client_for(ws) as c: yield c


def wait_end(c, job_id, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        j = c.get("/api/jobs/" + job_id).json()
        if j["state"] not in ("queued", "running"): return j
        time.sleep(0.05)
    raise AssertionError("job did not end")


# state and review files -------------------------------------------------------------------------------------------

def test_characters_and_state(ws, api):
    ws.build("choice")
    assert [c["id"] for c in api.get("/api/characters").json()] == ["tester"]
    st = api.get("/api/characters/tester").json()
    assert st["character"]["gate"]["kind"] == "motion" and len(st["stages"]) == 7
    assert api.get("/api/characters/nobody").status_code == 404


def test_manifest_matches_the_viewer_format(ws, api):
    ws.build("choice")
    m = api.get("/api/characters/tester/actions/attack/manifest.json").json()
    assert set(m) == {"title", "action", "glb", "audit", "samples"} and m["action"] == "attack"
    assert m["glb"].startswith("http://testserver/api/characters/tester/actions/attack/files/glb")
    glb = api.get(m["glb"])
    assert glb.status_code == 200 and glb.content == b"glTF" and glb.headers["content-type"] == "model/gltf-binary"
    assert api.get(m["audit"]).json()["result"] == "FAIL"


def test_manifest_without_samples_omits_the_key(ws, api):
    ws.build("choice"); os.remove(os.path.join(ws.work, "attack", "p", "audit_kf_s1", "audit_samples.json"))
    assert "samples" not in api.get("/api/characters/tester/actions/attack/manifest.json").json()


def test_no_review_files_yet(ws, api):
    ws.build("poses")
    assert api.get("/api/characters/tester/actions/attack/manifest.json").status_code == 404
    assert api.get("/api/characters/tester/actions/attack/manifest.json?source=merged").status_code == 404


def test_paths_outside_the_work_dir_are_refused(ws, api, tmp_path):
    ws.build("choice")
    secret = tmp_path / "secret.glb"; secret.write_bytes(b"TOPSECRET")
    p = os.path.join(ws.work, "attack", "choice.json"); ch = json.load(open(p))
    for glb in (str(secret), os.path.join(ws.work, "..", "..", "secret.glb")):
        ch["glb"] = glb; ws.write("attack/choice.json", ch)
        assert api.get("/api/characters/tester/actions/attack/manifest.json").status_code == 403
        r = api.get("/api/characters/tester/actions/attack/files/glb")
        assert r.status_code == 403 and b"TOPSECRET" not in r.content


def test_wrong_file_type_is_refused(ws, api):
    ws.build("choice")
    ch = json.load(open(os.path.join(ws.work, "attack", "choice.json"))); ch["glb"] = os.path.join(ws.work, "rig_ai_data.json")
    ws.write("attack/choice.json", ch)
    assert api.get("/api/characters/tester/actions/attack/files/glb").status_code == 403


@pytest.mark.parametrize("url,code", [
    ("/api/characters/tester/actions/..%2F..%2Fcharacter/files/glb", 404),
    ("/api/characters/tester/actions/walk%5C..%5C../files/glb", 404),
    ("/api/characters/tester/actions/attack/files/..%2Fchoice.json", 404),
    ("/api/characters/tester/actions/attack/files/glb?source=..%2F..", 422),
    ("/api/characters/tester/actions/nope/manifest.json", 404),
    ("/api/characters/tester/images/poses/0?action=..%2F..", 404),
    ("/api/characters/tester/images/poses/99?action=attack", 404),
    ("/api/characters/tester/images/other/0", 422),
])
def test_request_paths_cannot_escape(ws, api, url, code):
    ws.build("choice")
    assert api.get(url).status_code == code


def test_gate_images_by_index(ws, api):
    ws.build("poses")
    gate = api.get("/api/characters/tester").json()["character"]["gate"]
    r = api.get(gate["images"][0]["id"])
    assert r.status_code == 200 and r.content == b"png" and r.headers["content-type"] == "image/png"


def test_foreign_host_origin_and_content_type(ws, api):
    assert api.get("/api/health", headers={"host": "evil.example"}).status_code == 400   # DNS rebinding
    ws.build("choice")
    body = json.dumps({"gate": "motion", "action": "attack", "decision": "approve"})
    r = api.post("/api/characters/tester/verdicts", content=body, headers={"content-type": "application/json", "origin": "http://evil.example"})
    assert r.status_code == 403
    assert api.post("/api/characters/tester/verdicts", content=body, headers={"content-type": "text/plain"}).status_code == 415
    assert "approved" not in json.loads(ws.text())["actions"]["attack"]
    pre = api.options("/api/characters", headers={"origin": ORIGIN, "access-control-request-method": "GET"})
    assert pre.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-origin" not in api.get("/api/health", headers={"origin": "http://evil.example"}).headers


# verdicts ---------------------------------------------------------------------------------------------------------

def test_preview_then_approve_then_history(ws, api):
    ws.build("choice"); before = ws.text()
    req = {"gate": "motion", "action": "attack", "decision": "approve", "reviewer": "ann"}
    plan = api.post("/api/characters/tester/verdicts/preview", json=req).json()
    assert ws.text() == before and plan["changes"][0]["after"]["score"] == 6.21 and "+   \"approved\": {" in plan["changes"][0]["diff"]
    res = api.post("/api/characters/tester/verdicts", json={**req, "expected_config_sha": plan["config_sha"]})
    assert res.status_code == 200 and res.json()["entry"]["reviewer"] == "ann"
    assert json.loads(ws.text())["actions"]["attack"]["approved"]["score"] == 6.21
    assert api.post("/api/characters/tester/verdicts", json=req).status_code == 409   # nothing waits any more
    hist = api.get("/api/characters/tester/verdicts?action=attack").json()
    assert [(h["gate"], h["decision"]) for h in hist] == [("motion", "approve")]


def test_verdict_errors_have_a_detail(ws, api):
    ws.build("choice")
    r = api.post("/api/characters/tester/verdicts", json={"gate": "motion", "action": "attack", "decision": "reject"})
    assert r.status_code == 422 and "note" in r.json()["detail"]
    assert api.post("/api/characters/tester/verdicts", json={"gate": "motion", "decision": "maybe"}).status_code == 422


# runs -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code,state", [(0, "done"), (1, "failed"), (2, "waiting_for_review")])
def test_run_exit_codes(ws, code, state):
    with client_for(ws, fake_command(code)) as c:
        job = c.post("/api/characters/tester/runs", json={"from_stage": "rig", "to_stage": "merge"})
        assert job.status_code == 202
        end = wait_end(c, job.json()["id"])
        assert end["state"] == state and end["exit_code"] == code
        assert end["outcome"].startswith({0: "DONE", 1: "SystemExit", 2: "STOP:"}[code])


def test_run_flags_are_whitelisted(ws, api):
    for body in ({"from_stage": "--exit"}, {"to_stage": "rig; rm -rf /"}, {"command": "calc.exe"}):
        r = api.post("/api/characters/tester/runs", json=body)
        assert r.status_code in (422, 202)
        if r.status_code == 202:   # unknown keys are ignored: the configured command and flags only
            j = wait_end(api, r.json()["id"]); assert j["from_stage"] is None and j["to_stage"] is None
    assert api.post("/api/characters/tester/runs", json={"from_stage": "merge", "to_stage": "rig"}).status_code == 422


def test_stream_follows_the_log_to_the_end(ws, api):
    job = api.post("/api/characters/tester/runs", json={"to_stage": "ai"}).json()
    events = []; current = None
    with api.stream("GET", "/api/jobs/%s/events" % job["id"]) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "): current = line[7:]
            elif line.startswith("data: "): events.append((current, json.loads(line[6:])))
    texts = [d["text"] for e, d in events if e == "line"]
    assert texts[0].startswith("fake pipeline for tester") and any(t.startswith("STOP:") for t in texts)
    assert [d["n"] for e, d in events if e == "line"] == list(range(len(texts)))
    assert events[-1][0] == "end" and events[-1][1]["state"] == "waiting_for_review"
    with api.stream("GET", "/api/jobs/%s/events" % job["id"], headers={"last-event-id": "3"}) as r:   # resume after a reconnect
        resumed = [json.loads(ln[6:])["n"] for ln in r.iter_lines() if ln.startswith("data: ") and '"text"' in ln]
    assert resumed == list(range(4, len(texts)))


def test_queue_and_cancel(ws, tmp_path):
    other = tmp_path / "other"; other.mkdir()
    cfg2 = other / "character.json"; cfg2.write_text(ws.text().replace('"tester"', '"second"'), encoding="utf-8")
    s = Settings(characters=[Character("tester", ws.cfg), Character("second", str(cfg2))], pipeline_command=fake_command(2, 0.0, hang=True),
                 origins=[ORIGIN], reviewer="tests")
    with TestClient(create_app(s, allowed_hosts=("testserver",))) as c:
        a = c.post("/api/characters/tester/runs", json={}).json()
        b = c.post("/api/characters/second/runs", json={}).json()
        assert c.post("/api/characters/tester/runs", json={}).status_code == 409   # one active run per character
        t = time.time()
        while c.get("/api/jobs/" + a["id"]).json()["line_count"] < 3 and time.time() - t < 10: time.sleep(0.05)
        assert c.get("/api/jobs/" + a["id"]).json()["state"] == "running" and c.get("/api/jobs/" + b["id"]).json()["state"] == "queued"
        ws.build("choice")
        assert c.post("/api/characters/tester/verdicts", json={"gate": "motion", "action": "attack", "decision": "reject",
                                                               "note": "x"}).status_code == 409   # no verdicts during a run
        assert c.post("/api/jobs/%s/cancel" % b["id"], json={}).json()["state"] == "cancelled"   # queued: never starts
        c.post("/api/jobs/%s/cancel" % a["id"], json={})
        end = wait_end(c, a["id"])
        assert end["state"] == "cancelled" and end["outcome"] == "cancelled by the reviewer"
        assert c.get("/api/jobs/" + b["id"]).json()["started_at"] is None
        assert c.post("/api/jobs/nope/cancel", json={}).status_code == 404


def test_find_configs_scans_folders(ws, tmp_path):
    (tmp_path / "char" / "notes.json").write_text('{"x": 1}', encoding="utf-8")
    found = find_configs([str(tmp_path)])
    assert found == [ws.cfg] and [c.id for c in assign_ids([ws.cfg, ws.cfg])] == ["tester", "tester-2"]
