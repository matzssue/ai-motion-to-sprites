"""A synthetic character and work dir in a temp folder, built stage by stage with increasing file times."""
import json
import os
import sys
import time

import pytest

FAKE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fake_pipeline.py")

# indent 1, a comment key, a one-line action object: the verdict writer must keep all of it
CONFIG = """{
 "_about": "synthetic character for the service tests; paths relative to this file",
 "name": "tester",
 "model": "model.glb",
 "rig_input": "work/in.fbx",
 "rig": "work/rig.fbx",
 "rig_config": "rig.json",
 "work_dir": "work",
 "output": "out/tester_ai.glb",
 "walk_clip": "walk.fbx",
 "actions": {
  "walk": {"library": "walk.fbx"},
  "attack": {
   "ai": "attack.json",
   "_note": "keep me",
   "loop": false
  }
 },
 "kimodo": {"samples": 4, "seed": 0}
}
"""
MOTION = {"action": "attack", "phases": [{"duration": 1.0, "text": "a man swings"}], "key_poses": {"_c": "x", "start": 0, "hit": 12}}


class Workspace:
    def __init__(self, root):
        self.dir = os.path.join(str(root), "char"); self.work = os.path.join(self.dir, "work")
        self.cfg = os.path.join(self.dir, "character.json"); self.t = time.time() + 10_000   # newer than the pipeline scripts
        self.write("character.json", CONFIG, base=self.dir)
        self.write("rig.json", json.dumps({"joints": "joints.json"}), base=self.dir)
        self.write("attack.json", json.dumps(MOTION), base=self.dir)
        self.write("walk.fbx", "", base=self.dir)
        self.write("model.glb", "", base=self.dir)

    def write(self, rel, content="", base=None):
        p = os.path.join(base or self.work, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f: f.write(content if isinstance(content, str) else json.dumps(content))
        self.t += 10; os.utime(p, (self.t, self.t))
        return p

    def touch(self, p):
        self.t += 10; os.utime(p, (self.t, self.t))

    def audit(self, rel, result="OK", score=0.0):
        self.write(rel + "/audit.json", {"result": result, "score": score, "scores": {}, "errors": {}})
        self.write(rel + "/audit_samples.json", [{"t": 0.0, "v": {}}])

    def build(self, upto):
        """Files of every step up to `upto`, in pipeline order."""
        steps = ["prepare", "rig", "rig_ai", "calibration", "body", "poses", "poses_approved", "choice", "approve", "merge", "preview"]
        for s in steps[:steps.index(upto) + 1]: getattr(self, "_" + s)()

    def _prepare(self): self.write("in.fbx")
    def _rig(self): self.write("rig.fbx")

    def _rig_ai(self):
        self.write("rig_ai.glb"); self.write("rig_ai_data.json", {"prop": {}}); self.write("rig_ai_preview_side.png", "png")

    def _calibration(self): self.audit("calibration_walk"); self.write("calibration_ok.json", {"ok": True})

    def _body(self):
        self.write("attack/body.json", {"bvh": os.path.join(self.work, "attack", "e1", "body_s0.bvh"), "idx": 0, "score": 2.29,
                                        "merged": os.path.join(self.work, "attack", "e1", "p", "merged_body_s0.glb")})

    def _poses(self):
        self.write("attack/poses/poses.glb"); self.write("attack/poses/preview/attack.png", "png")
        self.write("attack/poses_v2/poses.glb")
        self.write("attack/poses_by_hand/poses.glb")   # pose_edit_scene.py --export

    def _poses_approved(self): self.write("attack/poses_approved.json", {"glb": "poses/poses.glb"})

    def _choice(self):
        d = os.path.join(self.work, "attack")
        self.write("attack/kf/kf_s1.bvh"); self.write("attack/kf/kf.npz")
        self.write("attack/p/clip_kf_s1.glb"); self.write("attack/p/merged_kf_s1.glb", "glTF")
        self.audit("attack/p/audit_kf_s1", "FAIL", 6.21)
        self.write("attack/choice.json", {
            "bvh": d + "\\kf\\kf_s1.bvh" if os.name == "nt" else d + "/kf/kf_s1.bvh", "npz": os.path.join(d, "kf", "kf.npz"),
            "clip": os.path.join(d, "p", "clip_kf_s1.glb"), "glb": os.path.join(d, "p", "merged_kf_s1.glb"), "score": 6.21,
            "audit": os.path.join(d, "p", "audit_kf_s1"), "pose_frames": [0, 12],
            "all": [[14.2, os.path.join(d, "kf", "kf_s0.bvh")], [6.21, os.path.join(d, "kf", "kf_s1.bvh")]]})

    def _approve(self):
        C = json.load(open(self.cfg, encoding="utf-8"))
        C["actions"]["attack"]["approved"] = {"bvh": "work/attack/kf/kf_s1.bvh", "score": 6.21, "date": "2026-11-19"}
        self.write("character.json", json.dumps(C, indent=1), base=self.dir)

    def _merge(self):
        self.write("tester_with_prop.glb"); self.audit("audit_walk"); self.audit("audit_attack", "FAIL", 6.0)
        self.write("report.json", {"walk": {"result": "OK", "score": 0}, "attack": {"result": "FAIL", "score": 6.0}})
        self.write("tester_ai.glb")

    def _preview(self):
        self.write("preview/done.json", "{}"); self.write("tester_ai.glb", base=os.path.join(self.dir, "out"))

    def text(self):
        return open(self.cfg, encoding="utf-8", newline="").read()


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path)


def fake_command(code=2, delay=0.0, hang=False):
    return [sys.executable, FAKE, "--exit", str(code), "--delay", str(delay)] + (["--hang"] if hang else [])
