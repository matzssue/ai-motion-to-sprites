"""Verdicts at the three human gates of character.py. An approval writes what the STOP message asks for:
rig -> nothing (a new run continues), poses -> <work>/<action>/poses_approved.json {"glb": ...},
motion -> actions.<action>.approved = {"bvh", "score", "date"} in character.json. A rejection writes nothing.
Every verdict is appended to the trail. Writes are planned first (the preview shows them), then applied atomically."""
import difflib
import hashlib
import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Optional

from . import trail
from .models import Change, TrailEntry, VerdictPlan, VerdictRequest, VerdictResult
from .json_edit import set_member
from .pipeline_lib import problems as schema_problems
from .status import Paths, derive, norm, poses_options, read_json

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class VerdictError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(str(detail)); self.status = status; self.detail = detail


@dataclass
class _Write:
    path: str
    data: bytes
    must_not_exist: bool = False


def _lock(cfg_path: str) -> threading.Lock:
    with _locks_guard: return _locks.setdefault(os.path.normcase(os.path.abspath(cfg_path)), threading.Lock())


def atomic_write(path: str, data: bytes) -> None:
    """Temp file in the same folder, flushed to disk, then os.replace: a reader sees the old file or the new one."""
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp): os.unlink(tmp)
        raise


def _diff(before: str, after: str, name: str) -> str:
    return "\n".join(difflib.unified_diff(before.splitlines(), after.splitlines(), name, name, lineterm=""))


def _plan(cfg_path: str, cid: str, req: VerdictRequest) -> tuple[VerdictPlan, list[_Write]]:
    raw = open(cfg_path, "rb").read(); sha = hashlib.sha256(raw).hexdigest()
    if req.expected_config_sha and req.expected_config_sha != sha:
        raise VerdictError(409, "character.json changed since this verdict was previewed; reload and look again")
    state = derive(cfg_path, cid)
    if state.character.problems and not state.character.work_dir:
        raise VerdictError(409, "character.json does not validate: %s" % "; ".join(state.character.problems))
    C = json.loads(raw.decode("utf-8")); P = Paths(cfg_path, C)
    if req.gate == "rig":
        if req.action: raise VerdictError(422, "the rig gate has no action")
        waiting = next((s for s in state.stages if s.name == "rig_ai"), None)
        if not waiting or waiting.status != "waiting": raise VerdictError(409, "no new AI rig waits for review")
        return VerdictPlan(request=req, changes=[], config_sha=sha, summary="%s the AI rig: nothing is written but the trail; "
                           "a new run continues past the rig" % ("approve" if req.decision == "approve" else "reject")), []
    n = req.action
    if not n or n not in C["actions"]: raise VerdictError(404, "no action %r in this character" % n)
    a = next(s for s in state.actions if s.name == n)
    if a.kind != "ai" or a.step != req.gate or a.status != "waiting":
        raise VerdictError(409, "action '%s' does not wait for a %s verdict (it is at %s, %s)" % (n, req.gate, a.step, a.status))
    if req.decision == "reject":
        return VerdictPlan(request=req, changes=[], config_sha=sha, summary="reject the %s of '%s': nothing is written but the trail"
                           % ("key poses" if req.gate == "poses" else "motion", n)), []
    D = P.action_dir(n)
    if req.gate == "poses":
        options = poses_options(P, n); pick = req.poses_glb or (options[0] if options else None)
        if pick not in options: raise VerdictError(422, "poses_glb must be one of %s" % options)
        target = os.path.join(D, "poses_approved.json")
        glb = os.path.normpath(os.path.join(D, pick)).replace("\\", "/")
        value = {"glb": glb, "_verdict": "approved %s in the review service" % date.today().isoformat()}
        text = json.dumps(value, ensure_ascii=False, indent=1) + "\n"
        change = Change(file=target, json_path="$", before=None, after=value, diff=_diff("", text, os.path.basename(target)))
        return (VerdictPlan(request=req, changes=[change], config_sha=sha, summary="approve the key poses of '%s' with %s" % (n, pick)),
                [_Write(target, text.encode("utf-8"), must_not_exist=True)])
    ch = read_json(os.path.join(D, "choice.json")) or {}
    value = {"bvh": norm(ch["bvh"]).replace("\\", "/"), "score": ch["score"], "date": date.today().isoformat()}
    before_text = raw.decode("utf-8")
    after_text = set_member(before_text, ["actions", n], "approved", value)
    bad = schema_problems(json.loads(after_text), "character")
    if bad: raise VerdictError(422, {"message": "the result would not match schemas/character.schema.json", "problems": bad})
    change = Change(file=cfg_path, json_path="$.actions.%s.approved" % n, before=C["actions"][n].get("approved"), after=value,
                    diff=_diff(before_text, after_text, os.path.basename(cfg_path)))
    return (VerdictPlan(request=req, changes=[change], config_sha=sha,
                        summary="approve the motion of '%s': sample %s, score %s" % (n, os.path.basename(value["bvh"]), value["score"])),
            [_Write(cfg_path, after_text.encode("utf-8"))])


def preview(cfg_path: str, cid: str, req: VerdictRequest) -> VerdictPlan:
    _check_note(req)
    return _plan(cfg_path, cid, req)[0]


def _check_note(req: VerdictRequest) -> None:
    if req.decision == "reject" and not req.note.strip(): raise VerdictError(422, "a rejection needs a note: what is wrong")


def apply(cfg_path: str, cid: str, req: VerdictRequest, reviewer: str) -> VerdictResult:
    _check_note(req)
    with _lock(cfg_path):
        plan, writes = _plan(cfg_path, cid, req)
        for w in writes:
            if w.must_not_exist and os.path.exists(w.path): raise VerdictError(409, "%s already exists" % os.path.basename(w.path))
        for w in writes: atomic_write(w.path, w.data)
        entry = TrailEntry(id=uuid.uuid4().hex[:12], at=trail.now_iso(), reviewer=(req.reviewer or reviewer).strip() or reviewer,
                           gate=req.gate, action=req.action, decision=req.decision, note=req.note.strip(), changes=plan.changes)
        C = json.loads(open(cfg_path, encoding="utf-8").read())
        trail.append(Paths(cfg_path, C).work, entry)
    return VerdictResult(entry=entry, summary=plan.summary)


def history(cfg_path: str, action: Optional[str] = None) -> list[TrailEntry]:
    C = json.loads(open(cfg_path, encoding="utf-8").read())
    entries = trail.read(Paths(cfg_path, C).work)
    return [e for e in entries if action is None or e.action == action]
