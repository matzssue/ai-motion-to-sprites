"""Whole character path: model -> rig -> AI rig -> actions (library + Kimodo) -> audit -> 8-direction preview.
python pipeline/character.py --character <dir>/character.json [--from stage] [--to stage]
Stages: prepare, rig, rig_ai, calibration, ai, merge, preview. A finished stage (output newer than its inputs) is skipped; --from forces.
STOPs for a human decision: a new AI rig, key poses (<work>/<action>/poses_approved.json), the motion (actions.<a>.approved).
Body sample and poses are made once: to redo, delete <action>/body.json or poses_approved.json.
Paths in character.json are relative to that file. Schemas: schemas/*.schema.json, example: examples/character.example.json.
All actions are put on the ground of the `walk` action (or, without one, of the first library action)."""
import argparse, glob, json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from config import KIMODO_PYTHON, script_path
from chain import blender, merge, audit, chain
from schema_check import load_character
from stages import NOISE, STAGES, fresh, keys

ap = argparse.ArgumentParser(description="Run the whole pipeline for one character, stopping at human review gates.")
ap.add_argument("--character", required=True); ap.add_argument("--from", dest="start", default=None, choices=STAGES)
ap.add_argument("--to", dest="end", default="preview", choices=STAGES)
A = ap.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
C = load_character(A.character)   # also the rig config and motion files: a bad key is named before any Blender step
BASE_DIR = os.path.dirname(os.path.abspath(A.character))


def r(p): return p if os.path.isabs(p) else os.path.normpath(os.path.join(BASE_DIR, p))


WORK = r(C["work_dir"]); os.makedirs(WORK, exist_ok=True)
RIG_AI = os.path.join(WORK, "rig_ai.glb")
RIG_DATA = RIG_AI.replace(".glb", "_data.json")
MERGED = os.path.join(WORK, "%s_merged.glb" % C["name"])
READY = os.path.join(WORK, "%s_ai.glb" % C["name"])
WALK = r(C.get("walk_clip") or C["actions"]["walk"]["library"])
OUTPUT = r(C["output"])
start = STAGES.index(A.start) if A.start else None
end = STAGES.index(A.end)


def stage(n, out, *inputs):
    """Whether to run stage n: within range and (forced by --from or output stale)."""
    i = STAGES.index(n)
    if i > end: return False
    if start is not None and i >= start: return True
    if fresh(out, *inputs): print("== %s: up to date (%s)" % (n, os.path.basename(out))); return False
    return True


def stop(msg):
    print("\nSTOP:", msg); sys.exit(2)


def python(script, *args, exe=sys.executable):
    print(">>", os.path.basename(script), flush=True)
    res = subprocess.run([exe, script, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("\n".join(res.stdout.splitlines()[-6:]))
    if res.returncode != 0: print(res.stderr[-3000:]); raise SystemExit("step %s failed" % script)


LIB_ACTIONS = [(n, r(a["library"])) for n, a in C["actions"].items() if "library" in a]
AI_ACTIONS = {n: a for n, a in C["actions"].items() if "ai" in a}
# prop in hands: an AI action (motion file "ai") or a library action with a grip file "motion" (walk with a crossbow: `no_aim`)
PROP_MOTION = {n: r(a.get("ai") or a["motion"]) for n, a in C["actions"].items() if a.get("prop") and (a.get("ai") or a.get("motion"))}
# combine_actions grounds every action on this one (a Kimodo clip stood 0.5 m lower than the library walk)
GROUND = "walk" if "walk" in C["actions"] else (LIB_ACTIONS[0][0] if LIB_ACTIONS else "")
PROP = None

# 1. model -> FBX for rigging (decimation, embedded texture)
if stage("prepare", r(C["rig_input"]), r(C["model"])):
    blender("prepare_for_rigging.py", "", "--src=" + r(C["model"]), "--out=" + r(C["rig_input"]), "--tris=25000", "--texture=1024")
    if not fresh(r(C["rig_input"]), r(C["model"])): raise SystemExit("prepare_for_rigging did not write %s" % C["rig_input"])
# 2. auto-rig (mixamorig skeleton + weights + joints)
if stage("rig", r(C["rig"]), r(C["rig_input"])):
    python(script_path("auto_rig.py"), "--src=" + r(C["rig_input"]), "--out=" + r(C["rig"]),
           "--template=" + r(C.get("auto_rig_template") or WALK))
# 3. AI rig: prop on its own bone, fingers from claws. A new one = look at the preview before going on
if stage("rig_ai", RIG_AI, r(C["rig"]), r(C["rig_config"]), script_path("prepare_rig.py")):
    blender("prepare_rig.py", "RIG OK", "--rig", r(C["rig"]), "--config", r(C["rig_config"]), "--out", RIG_AI, "--preview")
    stop("new AI rig. Look at %s (the whole prop red, the thumb red = really the thumb), then run again."
         % os.path.join(WORK, "rig_ai_preview_*.png"))
if end < STAGES.index("rig_ai"):
    print("\nDONE up to stage '%s'." % A.end); sys.exit(0)
DATA = json.load(open(RIG_DATA, encoding="utf-8"))
PROP = DATA.get("prop", {}).get("name")

# 4. calibration: library actions on the AI rig must pass the audit (prop where it was modelled)
CAL = os.path.join(WORK, "calibration.glb")
if LIB_ACTIONS and stage("calibration", os.path.join(WORK, "calibration_ok.json"), RIG_AI):
    merge(RIG_AI, LIB_ACTIONS, CAL)
    bad = {}
    for n, _ in LIB_ACTIONS:
        rep = audit(CAL, n, os.path.join(WORK, "calibration_" + n), PROP, rest_is_normal=True)
        if rep["result"] != "OK": bad[n] = rep["errors"]
    if bad: stop("calibration FAIL (%s) - a library motion penetrates on this rig; fix the rig/measurement first, not the AI motion." % ", ".join(bad))
    json.dump({"ok": True}, open(os.path.join(WORK, "calibration_ok.json"), "w"))


# 5. AI actions: body without hand constraints -> best sample -> STOP key poses for review ->
#    Kimodo through the poses -> every sample through the chain -> best. Hand constraints are not used: they hurt (README).
def pose_frames(R, motion):
    PK = R.get("key_poses")
    if not PK: stop("%s: no 'key_poses' (e.g. {\"hold\": 0, \"aim\": 44}, frames at 24 fps; the first = start and end)" % motion)
    return [int(v) for k, v in PK.items() if not k.startswith("_")]


def best_of(bvhs, motion, with_prop, out, loop=True):
    scores = []
    for bvh in bvhs:
        glb, rep = chain(RIG_AI, motion, bvh, out, WALK, with_prop=with_prop, loop=loop)
        scores.append((rep["score"], bvh, glb)); print("   %s: %s, score %.2f" % (os.path.basename(bvh), rep["result"], rep["score"]))
    return min(scores), scores


def ai_action(n, a):
    motion = r(a["ai"]); R = json.load(open(motion, encoding="utf-8")); with_prop = bool(a.get("prop")); lp = a.get("loop", True)
    if R["action"] != n: raise SystemExit("%s: 'action' in the motion file (%s) differs from the key in character.json (%s)" % (motion, R["action"], n))
    D = os.path.join(WORK, n); os.makedirs(D, exist_ok=True)
    choice = os.path.join(D, "choice.json")
    Z = a.get("approved")   # {"bvh", "score", "date"}: motion after the human verdict - no Kimodo, just the chain on this BVH
    if Z:
        if not stage("ai", choice, motion, RIG_AI, r(Z["bvh"])): return json.load(open(choice, encoding="utf-8"))
        (score, bvh, glb), _ = best_of([r(Z["bvh"])], motion, with_prop, os.path.join(D, "p"), lp)
        if score > Z["score"] + NOISE:
            stop("action '%s': the approved motion now scores %.2f instead of %.2f - the tool or the motion file changed "
                 "(compare_motion.py against the approved version)" % (n, score, Z["score"]))
        name = os.path.splitext(os.path.basename(bvh))[0]
        out = {"bvh": bvh, "clip": os.path.join(D, "p", "clip_%s.glb" % name), "glb": glb, "score": score, "approved": True}
        json.dump(out, open(choice, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return out
    fr = pose_frames(R, motion)
    K = C.get("kimodo", {}); count, seed = str(K.get("samples", 4)), str(K.get("seed", 0))
    emb = os.path.join(D, "emb.pt"); e1 = os.path.join(D, "e1")
    # 5a. body: samples without hand constraints, each through the full chain. Done once (a grip change in the motion file
    #     does not invalidate it); to redo, delete body.json
    body = os.path.join(D, "body.json")
    if not os.path.exists(body):
        python(script_path("kimodo_text.py"), "--motion", motion, "--out", emb, exe=KIMODO_PYTHON)
        python(script_path("kimodo_motion.py"), "--motion", motion, "--emb", emb, "--out", e1, "--name", "body",
               "--samples", count, "--seed", seed, exe=KIMODO_PYTHON)
        (o, bvh, _), sc = best_of(sorted(glob.glob(os.path.join(e1, "body_s*.bvh"))), motion, with_prop, os.path.join(e1, "p"), lp)
        name = os.path.splitext(os.path.basename(bvh))[0]
        json.dump({"bvh": bvh, "idx": int(name.rsplit("_s", 1)[1]), "score": o, "merged": os.path.join(e1, "p", "merged_%s.glb" % name),
                   "all": [(x, b) for x, b, _ in sc]}, open(body, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    BD = json.load(open(body, encoding="utf-8"))
    # 5b. key poses on this sample -> STOP for review. After the verdict write poses_approved.json {"glb": ...}
    appr = os.path.join(D, "poses_approved.json")
    if not os.path.exists(appr):
        P = os.path.join(D, "poses"); os.makedirs(P, exist_ok=True); g = os.path.join(P, "poses.glb"); ks = ",".join(map(str, fr))
        if with_prop:
            blender("prop_in_hands.py", "OK ", "--glb", BD["merged"], "--rig-data", RIG_DATA, "--motion", motion, "--out", g, "--frames", ks)
        else:
            shutil.copy(BD["merged"], g)
        blender("preview_8.py", "PREVIEW OK", "--glb", g, "--actions", n, "--frames", ks, "--out", os.path.join(P, "preview"))
        if with_prop: blender("hand_closeups.py", "CLOSEUPS OK", "--glb", g, "--action", n, "--frames", ks, "--out", os.path.join(P, "closeups"))
        stop("action '%s': key poses (fr. %s) on sample %s (score %.2f) for review: %s. Tune the grip and head with "
             "`variants.py --merged %s --frames %s`. After the verdict write %s with {\"glb\": <approved poses>} "
             "(the variant's parameters copied into the motion file) and run again."
             % (n, ks, os.path.basename(BD["bvh"]), BD["score"], P, BD["merged"], ks, appr))
    poses_glb = json.load(open(appr, encoding="utf-8"))["glb"]
    # 5c. motion through the poses: every sample through the chain, best by audit -> review_page.py -> STOP for the verdict
    if not stage("ai", choice, motion, RIG_AI, appr): return verdict(n, json.load(open(choice, encoding="utf-8")), D, with_prop)
    kf = os.path.join(D, "kf"); os.makedirs(kf, exist_ok=True); pj = os.path.join(kf, "poses.json")
    blender("keyposes_to_kimodo.py", "POSES OK", poses_glb, BD["merged"], BD["bvh"], pj, ",".join(map(str, fr)), n)
    if not os.path.exists(emb): python(script_path("kimodo_text.py"), "--motion", motion, "--out", emb, exe=KIMODO_PYTHON)
    python(script_path("kimodo_keyposes.py"), "--motion", motion, "--emb", emb, "--base", "%s:%d" % (os.path.join(e1, "body.npz"), BD["idx"]),
           "--poses", pj, "--keys", keys(R, fr, lp), "--out", kf, "--name", "kf", "--samples", count, "--seed", seed, exe=KIMODO_PYTHON)
    (score, bvh, glb), scores = best_of(sorted(glob.glob(os.path.join(kf, "kf_s*.bvh"))), motion, with_prop, os.path.join(D, "p"), lp)
    name = os.path.splitext(os.path.basename(bvh))[0]
    out = {"bvh": bvh, "npz": os.path.join(kf, "kf.npz"), "clip": os.path.join(D, "p", "clip_%s.glb" % name), "glb": glb,
           "score": score, "audit": os.path.join(D, "p", "audit_" + name), "pose_frames": fr, "all": [(o, b) for o, b, _ in scores]}
    json.dump(out, open(choice, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return verdict(n, out, D, with_prop)


def verdict(n, w, D, with_prop):
    """The audit does not close a motion (an approved clip had audit FAIL 1.40) - the human verdict on the review page does."""
    pg = os.path.join(D, "review")
    python(script_path("review_page.py"), "--glb", w["glb"], "--action", n, "--out", pg, "--title", "%s %s" % (C["name"], n),
           "--hand-frames", ",".join(map(str, w["pose_frames"])), *(["--prop", PROP] if with_prop else []),
           *([] if C["actions"][n].get("loop", True) else ["--no-loop"]))
    stop("action '%s': best sample %s, score %.2f (all: %s). Review page: %s. "
         "After approval set actions.%s.approved = {\"bvh\": \"%s\", \"score\": %.2f, \"date\": \"YYYY-MM-DD\"} in character.json "
         "and keep the BVH and %s." % (n, os.path.basename(w["bvh"]), w["score"], ", ".join("%.2f" % o for o, _ in w["all"]),
                                       os.path.join(pg, "page.html"), n, w["bvh"].replace("\\", "/"), w["score"], w["npz"]))


CHOICE = {n: ai_action(n, a) for n, a in AI_ACTIONS.items()} if end >= STAGES.index("ai") else {}

# 6. merge all actions, prop in hands per action, audit of every action
if (CHOICE or LIB_ACTIONS or PROP_MOTION) and end >= STAGES.index("merge") and stage("merge", READY, RIG_AI, *[w["clip"] for w in CHOICE.values()],
                                                                     *PROP_MOTION.values()):
    merge(RIG_AI, LIB_ACTIONS + [(n, w["clip"]) for n, w in CHOICE.items()], MERGED)
    # every action from the same MERGED, not chained: an export reorders vertices and the grip depends on it (combine_actions.py)
    after = {}
    for n, motion in PROP_MOTION.items():
        after[n] = os.path.join(WORK, "%s_after_%s.glb" % (C["name"], n))
        blender("prop_in_hands.py", "OK ", "--glb", MERGED, "--rig-data", RIG_DATA, "--motion", motion, "--out", after[n])
    cur = os.path.join(WORK, "%s_with_prop.glb" % C["name"])
    # always, also without a prop: combine_actions puts every action on the walk's ground (a Kimodo clip stood 0.5 m lower)
    if GROUND != "walk": print("== merge: no 'walk' action, grounding on '%s'" % (GROUND or "nothing"))
    blender("combine_actions.py", "COMBINE OK", "--base", MERGED, *("--action=%s=%s" % kv for kv in after.items()),
            "--ground=" + GROUND, "--out", cur)
    report = {}
    for n in C["actions"]:
        report[n] = audit(cur, n, os.path.join(WORK, "audit_" + n), PROP, rest_is_normal=n not in PROP_MOTION,
                          loop=C["actions"][n].get("loop", True))   # "loop": false for a one-shot action (death)
    json.dump({n: {"result": v["result"], "score": v["score"]} for n, v in report.items()},
              open(os.path.join(WORK, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # an approved action may have audit FAIL, but not worse than at the verdict
    appr = {n: a["approved"]["score"] for n, a in C["actions"].items() if a.get("approved")}
    bad = [n for n, v in report.items() if v["result"] != "OK" and not (n in appr and v["score"] <= appr[n] + NOISE)]
    if bad: stop("audit FAIL after merging: %s (details in %s). The audit does not close a motion: review_page.py for the verdict, after "
                 "approval actions.<action>.approved = {\"score\": <score>, \"date\": ...} in character.json." % (", ".join(
                     "%s %.2f" % (n, report[n]["score"]) for n in bad), os.path.join(WORK, "audit_<action>")))
    shutil.copy(cur, READY)

# 7. preview for the verdict: 8 directions of every action (only after a clean audit)
if stage("preview", os.path.join(WORK, "preview", "done.json"), READY):
    if not os.path.exists(READY): stop("no %s - run the merge stage first" % READY)
    blender("preview_8.py", "PREVIEW OK", "--glb", READY, "--actions", ",".join(C["actions"]), "--out", os.path.join(WORK, "preview"))
# the output is copied apart from the preview stage: a failed copy must not leave that stage looking finished
if end >= STAGES.index("preview") and os.path.exists(READY):
    if not fresh(OUTPUT, READY):
        os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
        shutil.copy(READY, OUTPUT)
    print("\nDONE:", OUTPUT, "| preview:", os.path.join(WORK, "preview"),
          "\nNext: review all 8 directions and all frames; after the verdict render your sprite sheets from the output GLB.")
