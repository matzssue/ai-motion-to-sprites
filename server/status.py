"""Pipeline state of one character, read-only from its files, by the rules of pipeline/character.py: the same file
names, the same freshness rule (lib/stages.fresh), the same order of stages and of AI actions (a run stops at the
first gate). Nothing here writes."""
import glob
import hashlib
import json
import os
from typing import Optional

from . import trail
from .models import ActionState, Approved, AuditSummary, CharacterSummary, Gate, ImageRef, PipelineState, SampleScore, StageState
from .pipeline_lib import NOISE, STAGES, fresh, load_character, rig_review, script_path


def norm(p: str) -> str:
    """A path as character.py wrote it (mixed separators on Windows) in this OS's form."""
    return os.path.normpath(p.replace("\\", "/"))


def read_json(p: str):
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return None


def config_sha(cfg_path: str) -> str:
    with open(cfg_path, "rb") as f: return hashlib.sha256(f.read()).hexdigest()


def why_stale(out: str, *inputs: str) -> str:
    if not os.path.exists(out): return "no %s yet" % os.path.basename(out)
    newer = [os.path.basename(i) for i in inputs if os.path.exists(i) and os.path.getmtime(i) > os.path.getmtime(out)]
    return "%s newer than %s" % (", ".join(newer), os.path.basename(out))


class Paths:
    """The file names of character.py for one config."""

    def __init__(self, cfg_path: str, C: dict):
        self.base = os.path.dirname(os.path.abspath(cfg_path)); self.C = C
        self.work = self.r(C["work_dir"])
        self.rig_ai = os.path.join(self.work, "rig_ai.glb")
        self.rig_data = self.rig_ai.replace(".glb", "_data.json")
        self.ready = os.path.join(self.work, "%s_ai.glb" % C["name"])
        self.with_prop = os.path.join(self.work, "%s_with_prop.glb" % C["name"])
        self.output = self.r(C["output"])
        self.calibration_ok = os.path.join(self.work, "calibration_ok.json")
        self.report = os.path.join(self.work, "report.json")
        self.preview_done = os.path.join(self.work, "preview", "done.json")

    def r(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.base, p))

    def action_dir(self, n: str) -> str:
        return os.path.join(self.work, n)

    def choice(self, n: str):
        return read_json(os.path.join(self.action_dir(n), "choice.json"))


def choice_files(P: Paths, n: str) -> Optional[dict]:
    """GLB and audit folder of an action's chosen sample (the audit chain() ran on that GLB), or None."""
    ch = P.choice(n)
    if not isinstance(ch, dict) or "glb" not in ch or "bvh" not in ch: return None
    glb = norm(ch["glb"]); sample = os.path.splitext(os.path.basename(norm(ch["bvh"])))[0]
    audit_dir = norm(ch["audit"]) if ch.get("audit") else os.path.join(os.path.dirname(glb), "audit_" + sample)
    return {"glb": glb, "audit": os.path.join(audit_dir, "audit.json"), "samples": os.path.join(audit_dir, "audit_samples.json"),
            "sample": sample, "choice": ch}


def merged_files(P: Paths, n: str) -> dict:
    """After the merge stage every action is audited on <name>_with_prop.glb into <work>/audit_<action>/."""
    d = os.path.join(P.work, "audit_" + n)
    return {"glb": P.with_prop, "audit": os.path.join(d, "audit.json"), "samples": os.path.join(d, "audit_samples.json")}


def gate_images(P: Paths, kind: str, action: Optional[str]) -> list[str]:
    """Preview images a reviewer needs at a gate, in a stable order (served by index, never by a requested path)."""
    if kind == "rig": return sorted(glob.glob(os.path.join(P.work, "rig_ai_preview_*.png")))
    if kind == "poses" and action:
        d = os.path.join(P.action_dir(action), "poses")
        return (sorted(glob.glob(os.path.join(d, "preview", "**", "*.png"), recursive=True))
                + sorted(glob.glob(os.path.join(d, "closeups", "**", "*.png"), recursive=True)))[:64]
    return []


def poses_options(P: Paths, n: str) -> list[str]:
    """poses/poses.glb (made by the run) first, then variants in poses_*/poses.glb, relative to the action folder."""
    D = P.action_dir(n)
    found = [os.path.join("poses", "poses.glb")] if os.path.exists(os.path.join(D, "poses", "poses.glb")) else []
    found += sorted(os.path.relpath(p, D) for p in glob.glob(os.path.join(D, "poses_*", "poses.glb")))
    return [p.replace("\\", "/") for p in found]


def _images(cid: str, P: Paths, kind: str, action: Optional[str]) -> list[ImageRef]:
    q = "?action=%s" % action if action else ""
    return [ImageRef(id="/api/characters/%s/images/%s/%d%s" % (cid, kind, i, q),
                     label=os.path.relpath(p, P.work).replace("\\", "/")) for i, p in enumerate(gate_images(P, kind, action))]


def _audit(p: str, source: str) -> Optional[AuditSummary]:
    a = read_json(p)
    if isinstance(a, dict) and "result" in a and "score" in a: return AuditSummary(result=a["result"], score=a["score"], source=source)
    return None


def _samples(all_scores) -> list[SampleScore]:
    out = []
    for item in all_scores or []:
        try: out.append(SampleScore(name=os.path.splitext(os.path.basename(norm(item[1])))[0], score=item[0]))
        except (TypeError, IndexError, ValueError): continue
    return out


def ai_action_state(cid: str, P: Paths, n: str, a: dict) -> ActionState:
    """One AI action by the branches of character.ai_action()."""
    C = P.C; motion = P.r(a["ai"]); D = P.action_dir(n); choice = os.path.join(D, "choice.json")
    st = dict(name=n, kind="ai", prop=bool(a.get("prop")), loop=a.get("loop", True))
    ch = choice_files(P, n)
    if ch:
        st["best"] = SampleScore(name=ch["sample"], score=ch["choice"].get("score", 0.0))
        st["samples"] = _samples(ch["choice"].get("all"))
        st["audit"] = _audit(ch["audit"], "best sample")
        if os.path.exists(ch["glb"]) and os.path.exists(ch["audit"]): st["review_sources"] = ["choice"]
    if os.path.exists(P.with_prop) and os.path.exists(merged_files(P, n)["audit"]): st.setdefault("review_sources", []).append("merged")
    Z = a.get("approved")
    if Z:
        st["approved"] = Approved(bvh=Z.get("bvh"), score=Z["score"], date=Z.get("date"))
        ins = [choice, motion, P.rig_ai] + ([P.r(Z["bvh"])] if Z.get("bvh") else [])
        if fresh(*ins): return ActionState(**st, step="approved", status="up_to_date", detail="approved %s" % (Z.get("date") or ""))
        return ActionState(**st, step="approved", status="stale",
                           detail="approved; the chain runs again on the approved BVH (%s)" % why_stale(*ins))
    R = read_json(motion)
    if not isinstance(R, dict): return ActionState(**st, step="body", status="error", detail="motion file %s is missing or not JSON" % a["ai"])
    if R.get("action") != n:
        return ActionState(**st, step="body", status="error", detail="'action' in %s is %r, not %r" % (a["ai"], R.get("action"), n))
    if not R.get("key_poses"):
        return ActionState(**st, step="body", status="error", detail="%s has no 'key_poses': the run stops before Kimodo" % a["ai"])
    frames = [int(v) for k, v in R["key_poses"].items() if not k.startswith("_")]
    body = os.path.join(D, "body.json")
    if not os.path.exists(body):
        return ActionState(**st, step="body", status="stale", detail="no body sample yet: the run samples %d bodies with Kimodo"
                           % C.get("kimodo", {}).get("samples", 4))
    BD = read_json(body) or {}
    appr = os.path.join(D, "poses_approved.json")
    if not os.path.exists(appr):
        poses_glb = os.path.join(D, "poses", "poses.glb")
        if fresh(poses_glb, body):
            gate = Gate(kind="poses", action=n, title="Review the key poses of '%s'" % n,
                        needs="Key poses (frames %s) on sample %s (score %.2f). Check the previews; tune the grip and head with "
                              "variants.py if needed. Approve with the poses GLB to use." % (
                                  ", ".join(map(str, frames)), os.path.basename(norm(BD.get("bvh", "?"))), BD.get("score", 0.0)),
                        writes="%s/poses_approved.json" % n, images=_images(cid, P, "poses", n), poses_options=poses_options(P, n))
            return ActionState(**st, step="poses", status="waiting", detail="key poses wait for review", gate=gate)
        return ActionState(**st, step="poses", status="stale", detail="the run makes the key poses and stops for review")
    if fresh(choice, motion, P.rig_ai, appr):
        c = st.get("best")
        gate = Gate(kind="motion", action=n, title="Approve the motion of '%s'" % n,
                    needs="Best sample %s, score %.2f (all: %s). The audit does not close a motion: watch it and decide." % (
                        c.name if c else "?", c.score if c else 0.0, ", ".join("%.2f" % s.score for s in st.get("samples", []))),
                    writes="actions.%s.approved in character.json" % n)
        return ActionState(**st, step="motion", status="waiting", detail="motion waits for the verdict", gate=gate)
    return ActionState(**st, step="motion", status="stale",
                       detail="Kimodo through the approved poses, then the verdict (%s)" % why_stale(choice, motion, P.rig_ai, appr))


def library_action_state(P: Paths, n: str, a: dict) -> ActionState:
    cal = _audit(os.path.join(P.work, "calibration_" + n, "audit.json"), "calibration")
    st = ActionState(name=n, kind="library", prop=bool(a.get("prop")), loop=a.get("loop", True), step="library", status="up_to_date",
                     detail="library clip", audit=cal)
    if os.path.exists(P.with_prop) and os.path.exists(merged_files(P, n)["audit"]): st.review_sources = ["merged"]
    return st


class _Walk:
    """Stages in order. A stale stage runs again and so do the ones after it; a waiting or failed stage, or a stale
    one that ends in a STOP, blocks the rest of the run."""

    def __init__(self):
        self.stages: list[StageState] = []; self.rerun_from = None; self.blocked_by = None

    def put(self, name, status, detail, out=None, stops=False):
        if status != "skipped":
            if self.blocked_by: status, detail = "blocked", "after %s" % self.blocked_by
            elif status == "up_to_date" and self.rerun_from: status, detail = "stale", "runs again after %s" % self.rerun_from
        self.stages.append(StageState(name=name, status=status, detail=detail, output=out))
        if status == "stale" and not self.rerun_from: self.rerun_from = name
        if status in ("waiting", "failed") or (status == "stale" and stops): self.blocked_by = name
        return status


def derive(cfg_path: str, cid: str, entries: Optional[list] = None) -> PipelineState:
    sha = config_sha(cfg_path)
    try:
        C = load_character(cfg_path)   # the same validation character.py runs before anything else
    except SystemExit as e:
        C = read_json(cfg_path)
        name = C.get("name") if isinstance(C, dict) and isinstance(C.get("name"), str) else cid
        summary = CharacterSummary(id=cid, name=name, config_path=cfg_path, problems=[str(e)])
        return PipelineState(character=summary, config_sha=sha, actions=[],
                             stages=[StageState(name=s, status="blocked", detail="character.json does not validate") for s in STAGES])
    P = Paths(cfg_path, C); W = _Walk(); problems: list[str] = []; rig_gate = None
    if entries is None: entries = trail.read(P.work)
    acts = C["actions"]
    lib = [n for n, a in acts.items() if "library" in a]
    ai = [n for n, a in acts.items() if "ai" in a]
    prop_motion = [P.r(a.get("ai") or a["motion"]) for a in acts.values() if a.get("prop") and (a.get("ai") or a.get("motion"))]
    states = {n: ai_action_state(cid, P, n, a) if "ai" in a else library_action_state(P, n, a) for n, a in acts.items()}
    rel = lambda p: os.path.relpath(p, P.work).replace("\\", "/") if p.startswith(P.work) else os.path.basename(p)  # noqa: E731

    ins = (P.r(C["rig_input"]), P.r(C["model"]))
    W.put("prepare", "up_to_date" if fresh(*ins) else "stale", "up to date" if fresh(*ins) else why_stale(*ins), rel(ins[0]))
    ins = (P.r(C["rig"]), P.r(C["rig_input"]))
    W.put("rig", "up_to_date" if fresh(*ins) else "stale", "up to date" if fresh(*ins) else why_stale(*ins), rel(ins[0]))

    ins = (P.rig_ai, P.r(C["rig"]), P.r(C["rig_config"]), script_path("prepare_rig.py"))
    if not fresh(*ins):
        W.put("rig_ai", "stale", why_stale(*ins) + "; the run stops for the AI rig review", rel(P.rig_ai), stops=True)
    else:
        t = os.path.getmtime(P.rig_ai)
        later = ([P.calibration_ok, P.ready] + [os.path.join(P.work, "calibration_" + n, "audit.json") for n in lib]
                 + [os.path.join(P.action_dir(n), f) for n in ai for f in ("body.json", "choice.json")])   # the run went past the rig
        passed = any(os.path.exists(p) and os.path.getmtime(p) >= t for p in later) or any(
            e.gate == "rig" and e.decision == "approve" and trail.timestamp(e) >= int(t) for e in entries)
        if passed: W.put("rig_ai", "up_to_date", "up to date", rel(P.rig_ai))
        else:
            gate = Gate(kind="rig", title="Review the new AI rig",
                        needs="Look at the rig previews: %s. Approve to note it in the trail and run again; reject with a "
                              "note and fix the rig config." % rig_review("prop" in (read_json(P.rig_data) or {})),
                        images=_images(cid, P, "rig", None))
            if W.put("rig_ai", "waiting", "new AI rig waits for review", rel(P.rig_ai)) == "waiting": rig_gate = gate
        if not os.path.exists(P.rig_data): problems.append("%s is missing: the run needs it after the rig_ai stage" % rel(P.rig_data))

    if not lib: W.put("calibration", "skipped", "no library actions")
    elif fresh(P.calibration_ok, P.rig_ai): W.put("calibration", "up_to_date", "up to date", rel(P.calibration_ok))
    else:
        bad = [n for n in lib if (lambda a: a and a.get("result") != "OK")(read_json(os.path.join(P.work, "calibration_" + n, "audit.json")))
               and fresh(os.path.join(P.work, "calibration_" + n, "audit.json"), P.rig_ai)]
        if bad: W.put("calibration", "failed", "calibration FAIL (%s): a library motion penetrates on this rig; fix the rig first"
                      % ", ".join(bad), rel(P.calibration_ok))
        else: W.put("calibration", "stale", why_stale(P.calibration_ok, P.rig_ai), rel(P.calibration_ok))

    ai_gate = None
    if not ai: W.put("ai", "skipped", "no AI actions")
    else:
        first = next((states[n] for n in ai if states[n].status != "up_to_date"), None)
        if first is None: W.put("ai", "up_to_date", "%d AI action(s) approved and up to date" % len(ai))
        elif first.status == "waiting": W.put("ai", "waiting", "%s: %s" % (first.name, first.detail)); ai_gate = first.gate
        elif first.status == "error": W.put("ai", "failed", "%s: %s" % (first.name, first.detail))
        else: W.put("ai", "stale", "%s: %s" % (first.name, first.detail), stops=first.step != "approved")

    clips = [norm(c["clip"]) for c in (P.choice(n) for n in ai) if isinstance(c, dict) and c.get("clip")]
    ins = (P.ready, P.rig_ai, *clips, *prop_motion)
    if not (ai or lib or prop_motion): W.put("merge", "skipped", "no actions")
    elif fresh(*ins): W.put("merge", "up_to_date", "up to date", rel(P.ready))
    else:
        rep = read_json(P.report) if fresh(P.report, *ins[1:]) else None
        appr = {n: a["approved"]["score"] for n, a in acts.items() if a.get("approved")}
        bad = [n for n, v in (rep or {}).items() if isinstance(v, dict) and v.get("result") != "OK"
               and not (n in appr and v.get("score", 0) <= appr[n] + NOISE)]
        if bad: W.put("merge", "failed", "audit FAIL after merging: %s; approve the action or fix it" % ", ".join(
            "%s %.2f" % (n, rep[n].get("score", 0)) for n in bad), rel(P.ready))
        else: W.put("merge", "stale", why_stale(*ins), rel(P.ready))
    rep = read_json(P.report)
    for n, v in (rep or {}).items():
        if n in states and isinstance(v, dict) and "result" in v:
            states[n].merged_audit = AuditSummary(result=v["result"], score=v.get("score", 0.0), source="after merge")

    pv = W.put("preview", "up_to_date" if fresh(P.preview_done, P.ready) else "stale",
               "up to date" if fresh(P.preview_done, P.ready) else why_stale(P.preview_done, P.ready), rel(P.preview_done))
    done = pv == "up_to_date" and all(s.status in ("up_to_date", "skipped") for s in W.stages) and fresh(P.output, P.ready)

    waiting = next((s for s in W.stages if s.status == "waiting"), None)
    gate = None
    if waiting: gate = rig_gate if waiting.name == "rig_ai" else ai_gate
    stale = next((s.name for s in W.stages if s.status == "stale"), None)
    summary = CharacterSummary(id=cid, name=C["name"], config_path=cfg_path, work_dir=P.work, gate=gate, stale_stage=stale,
                               done=done, problems=problems)
    return PipelineState(character=summary, config_sha=sha, stages=W.stages, actions=list(states.values()))
