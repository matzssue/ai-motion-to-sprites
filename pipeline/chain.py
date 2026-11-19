"""Blender chain of AI motion for one sample: retarget -> merge with the walk -> prop in hands -> audit.
character.py drives a whole character (model -> all actions); this is its building block, used alone to fix one sample.
python pipeline/chain.py --rig rig_ai.glb --motion <motion>.json --bvh x_s0.bvh --walk walk.fbx --out dir
    [--no-prop] [--from retarget|merge|prop|audit] [--skeleton mixamo|profile.json]"""
import argparse, json, os, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from config import BLENDER, script_path
from schema_check import load as load_config, load_skeleton

IMPORTANT = ("smoothed", "RETARGET", "merge_actions", "pass", "OK", "AUDIT", "  FAIL", "  rest", "  score", "  no limit", "  skipped",
             "skeleton", "fingers: skipped", "stock",
             "closeups", "MAX", "RIG OK", "prop ", "grip ", "LIMIT", "PROP POSE", "time", "DIFF", "COMPARE", "PREVIEW", "CLOSEUPS", "action ")


def blender(script, marker, *args):
    """Success = a line starting with `marker` in the output; a Traceback says nothing (user add-ons print one on every exit)."""
    path = script if os.path.isabs(script) else script_path(script)
    print(">>", os.path.basename(script), flush=True)
    r = subprocess.run([BLENDER, "-b", "--python", path, "--", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("\n".join(l for l in r.stdout.splitlines() if l.startswith(IMPORTANT)), flush=True)
    if not any(l.startswith(marker) for l in r.stdout.splitlines()):
        print(r.stdout[-3000:], r.stderr[-3000:]); raise SystemExit("step %s failed" % script)
    return r.stdout


def merge(rig, actions, out, skeleton=None):
    """actions: [(name, file)]. The AI clip action must be named differently than the library action (merge rejects name clashes)."""
    blender("merge_actions.py", "merge_actions: " + out, "--base=" + rig, *("--anim=%s=%s" % a for a in actions), "--out=" + out,
            *(["--skeleton=" + skeleton] if skeleton else []))


def skel(skeleton):
    """--skeleton arguments; none for the default (a config without `skeleton` runs exactly as before)."""
    return ["--skeleton", skeleton] if skeleton else []


def audit(glb, action, out, prop=None, rest_is_normal=False, loop=True, skeleton=None):
    args = ["--glb", glb, "--action", action, "--out", out] + (["--prop", prop] if prop else []) + skel(skeleton)
    blender("motion_audit.py", "AUDIT", *args, *(["--rest-is-normal"] if rest_is_normal else []), *([] if loop else ["--no-loop"]))
    return json.load(open(os.path.join(out, "audit.json"), encoding="utf-8"))


def chain(rig, motion, bvh, out, walk, with_prop=True, start="retarget", loop=True, skeleton=None):
    """Returns (glb, audit report)."""
    R = json.load(open(motion, encoding="utf-8")); action = R["action"]
    os.makedirs(out, exist_ok=True)
    name = os.path.splitext(os.path.basename(bvh))[0]
    clip, merged, ready = (os.path.join(out, "%s_%s.glb" % (p, name)) for p in ("clip", "merged", "prop"))
    data = rig.replace(".glb", "_data.json")
    steps = ["retarget", "merge", "prop", "audit"]; k = steps.index(start)
    if k <= 0: blender("soma_to_mixamo.py", "RETARGET OK", bvh, rig, clip, "ai_source", str(R.get("loop_blend_s", 0)), *skel(skeleton))
    # an AI walk is named like the library walk - merge rejects name clashes
    if k <= 1: merge(rig, [("walk" if action != "walk" else "walk_library", walk), (action, clip)], merged, skeleton)
    result = merged
    prop = json.load(open(data, encoding="utf-8"))["prop"]["name"] if with_prop else None
    if with_prop:
        if k <= 2: blender("prop_in_hands.py", "OK ", "--glb", merged, "--rig-data", data, "--motion", motion, "--out", ready,
                           *skel(skeleton))
        result = ready
    return result, audit(result, action, os.path.join(out, "audit_" + name), prop, loop=loop, skeleton=skeleton)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Run retarget -> merge -> prop in hands -> audit for one Kimodo sample.")
    ap.add_argument("--rig", required=True); ap.add_argument("--motion", required=True); ap.add_argument("--bvh", required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--walk", required=True, help="library walk clip (Mixamo skeleton)")
    ap.add_argument("--no-prop", action="store_true"); ap.add_argument("--from", dest="start", default="retarget", choices=["retarget", "merge", "prop", "audit"])
    ap.add_argument("--skeleton", default=None, help="skeleton profile of the rig: built-in name or JSON path (default mixamo)")
    A = ap.parse_args()
    load_config(A.motion, "motion", () if A.no_prop else ("grip",))
    if A.skeleton: load_skeleton(A.skeleton)   # a bad profile is named before any Blender step
    glb, rep = chain(*(os.path.abspath(p) for p in (A.rig, A.motion, A.bvh, A.out, A.walk)), not A.no_prop, A.start,
                     skeleton=A.skeleton and (A.skeleton if not A.skeleton.endswith(".json") else os.path.abspath(A.skeleton)))
    print("RESULT", glb, rep["result"], "score", rep["score"])
