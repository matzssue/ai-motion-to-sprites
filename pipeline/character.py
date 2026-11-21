"""Whole character path: model -> rig -> AI rig -> actions (library + Kimodo) -> audit -> 8-direction preview.
python pipeline/character.py --character <dir>/character.json [--from stage] [--to stage]
Stages: prepare, rig, rig_ai, calibration, ai, merge, preview. A finished stage (output newer than its inputs) is skipped; --from forces.
STOPs for a human decision: a new AI rig, key poses (<work>/<action>/poses_approved.json), the motion (actions.<a>.approved).
Body sample and poses are made once: to redo, delete <action>/body.json or poses_approved.json. The automatic sample is the
lowest audit score among the samples whose hands moved (stages.pick); `--sample attack=2` takes sample 2 of the action's
latest batch instead (body samples before the poses are approved, Kimodo-through-poses samples after).
Paths in character.json are relative to that file. Schemas: schemas/*.schema.json, example: examples/character.example.json.
Rig: `auto_rig_template`, else the library walk, is the Mixamo template of auto_rig (`mixamorig:*` skeleton). With neither,
or with "skeleton": "amts", auto_rig builds the own skeleton (skeletons/amts.json) and every later stage uses that profile.
An action whose motion file names a `recipe` (pipeline/recipes/README.md: a weapon in the hands) gets it in the chain and again
on the combined file of the merge stage; `"prop": true` is the experimental two-handed solver instead.
All actions are put on the ground of `ground` (default: the `walk` action, else the first library action, else the rest pose's feet)."""
import argparse, glob, json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from config import KIMODO_PYTHON, script_path
from chain import blender, merge, audit, chain, run_recipe, skel
from schema_check import load_character
from stages import NOISE, STAGES, fresh, keys, pick, rig_review
import bvh as BV

ap = argparse.ArgumentParser(description="Run the whole pipeline for one character, stopping at human review gates.")
ap.add_argument("--character", required=True); ap.add_argument("--from", dest="start", default=None, choices=STAGES)
ap.add_argument("--to", dest="end", default="preview", choices=STAGES)
ap.add_argument("--sample", action="append", default=[], metavar="ACTION=N",
                help="take sample N of the action's latest batch instead of the automatic choice (repeatable)")
A = ap.parse_args()
SAMPLE = {}
for _s in A.sample:
    _n, _, _i = _s.partition("=")
    if not _i.isdigit(): ap.error("--sample takes ACTION=N, e.g. attack=2 (got %r)" % _s)
    SAMPLE[_n] = int(_i)
sys.stdout.reconfigure(encoding="utf-8")
C = load_character(A.character)   # also the rig config and motion files: a bad key is named before any Blender step
BASE_DIR = os.path.dirname(os.path.abspath(A.character))


def r(p): return p if os.path.isabs(p) else os.path.normpath(os.path.join(BASE_DIR, p))


WORK = r(C["work_dir"]); os.makedirs(WORK, exist_ok=True)
RIG_AI = os.path.join(WORK, "rig_ai.glb")
RIG_DATA = RIG_AI.replace(".glb", "_data.json")
MERGED = os.path.join(WORK, "%s_merged.glb" % C["name"])
READY = os.path.join(WORK, "%s_ai.glb" % C["name"])
_walk = C.get("walk_clip") or C["actions"].get("walk", {}).get("library")
WALK = r(_walk) if _walk else None   # None: AI samples are merged alone (no library clip anywhere)
OUTPUT = r(C["output"])
# skeleton profile of `rig` (built-in name or path); None = Mixamo, and the scripts get no --skeleton (as before profiles)
SKEL = C.get("skeleton") and (r(C["skeleton"]) if C["skeleton"].lower().endswith(".json") else C["skeleton"])
TEMPLATE = C.get("auto_rig_template") or WALK
OWN_RIG = not C.get("auto_rig_template") and (not TEMPLATE or SKEL == "amts")
if OWN_RIG: SKEL = SKEL or "amts"
SK = skel(SKEL)
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
if OWN_RIG and LIB_ACTIONS:
    # merge_actions copies a clip bone's armature-space pose: right only between skeletons with the same rest frames
    raise SystemExit("library clips (%s) are Mixamo-skeleton clips and cannot go onto the own skeleton (amts): give "
                     "`auto_rig_template` for a Mixamo rig, or make these actions with Kimodo (`ai`)" % ", ".join(n for n, _ in LIB_ACTIONS))
AI_ACTIONS = {n: a for n, a in C["actions"].items() if "ai" in a}
if set(SAMPLE) - set(AI_ACTIONS): ap.error("--sample: %s is not an AI action of this character" % ", ".join(sorted(set(SAMPLE) - set(AI_ACTIONS))))
# prop in hands: an AI action (motion file "ai") or a library action with a grip file "motion" (walk with a crossbow: `no_aim`)
PROP_MOTION = {n: r(a.get("ai") or a["motion"]) for n, a in C["actions"].items() if a.get("prop") and (a.get("ai") or a.get("motion"))}
# a recipe named by the action's motion file (pipeline/recipes/README.md): run on the combined file, after the prop solver
RECIPE = {}
for _n, _a in C["actions"].items():
    _m = _a.get("ai") or _a.get("motion")
    if _m and os.path.exists(r(_m)) and "recipe" in json.load(open(r(_m), encoding="utf-8")): RECIPE[_n] = r(_m)
# combine_actions grounds every action on this one (a Kimodo clip stood 0.5 m lower than the library walk);
# @rest = the rest pose's feet, for a character without any library clip
GROUND = C.get("ground") or ("walk" if "walk" in C["actions"] else (LIB_ACTIONS[0][0] if LIB_ACTIONS else "@rest"))
PROP = None

# 1. model -> FBX for rigging (decimation, embedded texture); a separate prop mesh goes in marked, out of joint detection
PROP_MODEL = [r(C["prop_model"])] if C.get("prop_model") else []
if stage("prepare", r(C["rig_input"]), r(C["model"]), *PROP_MODEL):
    blender("prepare_for_rigging.py", "", "--src=" + r(C["model"]), "--out=" + r(C["rig_input"]), "--tris=25000", "--texture=1024",
            *["--prop=" + x for x in PROP_MODEL])
    if not fresh(r(C["rig_input"]), r(C["model"]), *PROP_MODEL): raise SystemExit("prepare_for_rigging did not write %s" % C["rig_input"])
# 2. auto-rig (skeleton + weights + joints): own skeleton, or mixamorig from the template
if stage("rig", r(C["rig"]), r(C["rig_input"])):
    python(script_path("auto_rig.py"), "--src=" + r(C["rig_input"]), "--out=" + r(C["rig"]),
           *([] if OWN_RIG else ["--template=" + r(TEMPLATE)]), *(["--allow-asymmetry"] if C.get("rig_asymmetric") else []))
# 3. AI rig: prop on its own bone, fingers from claws. A new one = look at the preview before going on
if stage("rig_ai", RIG_AI, r(C["rig"]), r(C["rig_config"]), script_path("prepare_rig.py")):
    blender("prepare_rig.py", "RIG OK", "--rig", r(C["rig"]), "--config", r(C["rig_config"]), "--out", RIG_AI, "--preview", *SK)
    stop("new AI rig. Look at %s (%s), then run again."
         % (os.path.join(WORK, "rig_ai_preview_*.png"), rig_review("prop" in json.load(open(RIG_DATA, encoding="utf-8")))))
if end < STAGES.index("rig_ai"):
    print("\nDONE up to stage '%s'." % A.end); sys.exit(0)
DATA = json.load(open(RIG_DATA, encoding="utf-8"))
PROP = DATA.get("prop", {}).get("name")

# 4. calibration: library actions on the AI rig must pass the audit (prop where it was modelled)
CAL = os.path.join(WORK, "calibration.glb")
if LIB_ACTIONS and stage("calibration", os.path.join(WORK, "calibration_ok.json"), RIG_AI):
    merge(RIG_AI, LIB_ACTIONS, CAL, SKEL)
    bad = {}
    for n, _ in LIB_ACTIONS:
        rep = audit(CAL, n, os.path.join(WORK, "calibration_" + n), PROP, rest_is_normal=True, skeleton=SKEL)
        if rep["result"] != "OK": bad[n] = rep["errors"]
    if bad: stop("calibration FAIL (%s) - a library motion penetrates on this rig; fix the rig/measurement first, not the AI motion." % ", ".join(bad))
    json.dump({"ok": True}, open(os.path.join(WORK, "calibration_ok.json"), "w"))


# 5. AI actions: body without hand constraints -> best sample -> STOP key poses for review ->
#    Kimodo through the poses -> every sample through the chain -> best. Hand constraints are not used: they hurt (README).
def pose_names(R):
    return [k for k in R["key_poses"] if not k.startswith("_")]


def pose_frames(R, motion):
    PK = R.get("key_poses")
    if not PK: stop("%s: no 'key_poses' (e.g. {\"hold\": 0, \"aim\": 44}, frames at 24 fps; the first = start and end)" % motion)
    return [int(v) for k, v in PK.items() if not k.startswith("_")]


def hand_range(bvh, R):
    return max(BV.activity(*BV.joints(bvh), R)["range"].values())


def best_of(bvhs, motion, with_prop, out, loop=True, key_poses=None):
    """Every sample through the chain -> (chosen (score, bvh, glb, range), all of them). `range` = the larger hand's extent
    against the hips over the raw clip (m): a sample that stood still must not win on a clean audit (stages.pick)."""
    R = json.load(open(motion, encoding="utf-8")); scores = []
    for bvh in bvhs:
        glb, rep = chain(RIG_AI, motion, bvh, out, WALK, with_prop=with_prop, loop=loop, skeleton=SKEL, key_poses=key_poses)
        m = hand_range(bvh, R)
        scores.append((rep["score"], bvh, glb, m))
        print("   %s: %s, score %.2f, hands moved %.2f m" % (os.path.basename(bvh), rep["result"], rep["score"], m))
    return scores[pick([(o, m) for o, _, _, m in scores])], scores


def listed(all_, R):
    """`all` of body.json / choice.json -> [(score, bvh, range)]; files from before the range get it from their BVH."""
    return [(x[0], x[1], x[2] if len(x) > 2 else hand_range(x[1], R)) for x in all_]


def by_hand(n, all_, R, what):
    """--sample n=i: sample i of `all_` -> ((score, bvh, range), all rows), or a STOP naming the samples there are."""
    i = SAMPLE[n]; rows = listed(all_, R)
    hit = [x for x in rows if os.path.splitext(os.path.basename(x[1]))[0].endswith("_s%d" % i)]
    if not hit: stop("action '%s': --sample %s=%d: no such %s sample (there are: %s)" % (
        n, n, i, what, ", ".join(os.path.splitext(os.path.basename(x[1]))[0] for x in rows)))
    return hit[0], rows


def write_body(path, e1, score, bvh, rows, how):
    name = os.path.splitext(os.path.basename(bvh))[0]
    json.dump({"bvh": bvh, "idx": int(name.rsplit("_s", 1)[1]), "score": score, "merged": os.path.join(e1, "p", "merged_%s.glb" % name),
               "all": [list(x) for x in rows], "pick": how}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def samples_line(rows):
    """[(score, bvh, range)] -> 's0 1.18 / 0.37 m, ...' (audit score / how far the hands moved)."""
    return ", ".join("%s %.2f%s" % (os.path.splitext(os.path.basename(b))[0].rsplit("_", 1)[-1], o, "" if m is None else " / %.2f m" % m)
                     for o, b, m in rows)


def ai_action(n, a):
    motion = r(a["ai"]); R = json.load(open(motion, encoding="utf-8")); with_prop = bool(a.get("prop")); lp = a.get("loop", True)
    if R["action"] != n: raise SystemExit("%s: 'action' in the motion file (%s) differs from the key in character.json (%s)" % (motion, R["action"], n))
    D = os.path.join(WORK, n); os.makedirs(D, exist_ok=True)
    choice = os.path.join(D, "choice.json")
    Z = a.get("approved")   # {"bvh", "score", "date"}: motion after the human verdict - no Kimodo, just the chain on this BVH
    if Z:
        if not stage("ai", choice, motion, RIG_AI, r(Z["bvh"])): return json.load(open(choice, encoding="utf-8"))
        # "key_hands": approved after key_hands.py put the key poses' hand rotation back (older verdicts ran without it)
        kp = None
        if Z.get("key_hands"):
            kp = (json.load(open(os.path.join(D, "poses_approved.json"), encoding="utf-8"))["glb"], pose_frames(R, motion))
        (score, bvh, glb, _), _ = best_of([r(Z["bvh"])], motion, with_prop, os.path.join(D, "p"), lp, kp)
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
        (o, bvh, _, _), sc = best_of(sorted(glob.glob(os.path.join(e1, "body_s*.bvh"))), motion, with_prop, os.path.join(e1, "p"), lp)
        write_body(body, e1, o, bvh, [(x, b, m) for x, b, _, m in sc], "auto")
    BD = json.load(open(body, encoding="utf-8"))
    appr = os.path.join(D, "poses_approved.json")
    if n in SAMPLE and not os.path.exists(appr):
        (o, bvh, _), rows = by_hand(n, BD["all"], R, "body")
        if bvh != BD["bvh"]: print("== %s: body sample %s by hand (--sample)" % (n, os.path.basename(bvh)))
        write_body(body, e1, o, bvh, rows, "by hand"); BD = json.load(open(body, encoding="utf-8"))
    # 5b. key poses on this sample -> STOP for review. After the verdict write poses_approved.json {"glb": ...}
    if not os.path.exists(appr):
        P = os.path.join(D, "poses"); os.makedirs(P, exist_ok=True); g = os.path.join(P, "poses.glb"); ks = ",".join(map(str, fr))
        if with_prop:
            blender("prop_in_hands.py", "OK ", "--glb", BD["merged"], "--rig-data", RIG_DATA, "--motion", motion, "--out", g, "--frames", ks, *SK)
        else:
            shutil.copy(BD["merged"], g)
        blender("preview_8.py", "PREVIEW OK", "--glb", g, "--actions", n, "--frames", ks, "--out", os.path.join(P, "preview"))
        if with_prop: blender("hand_closeups.py", "CLOSEUPS OK", "--glb", g, "--action", n, "--frames", ks, "--out", os.path.join(P, "closeups"), *SK)
        # a scene to fix the poses by hand, one per sample (kept once made: it may hold the author's posing)
        HB = os.path.join(D, "poses_by_hand"); sname = os.path.splitext(os.path.basename(BD["bvh"]))[0]
        eb = os.path.join(HB, "edit_%s.blend" % sname); hg = os.path.join(HB, "poses.glb")
        blender("pose_edit_scene.py", "EDIT SCENE", "--glb", g, "--action", n, "--frames", ks, "--names", ",".join(pose_names(R)),
                "--sample", BD["bvh"], "--out", eb)
        stop("action '%s': key poses (fr. %s) on sample %s (%s; score / hands moved: %s) for review: %s. Tune the grip and head "
             "with `variants.py --merged %s --frames %s`; another sample: --sample %s=N. To pose by hand: open %s in Blender "
             "(a marker on each key frame, auto-key on), change only those frames, save, then `blender -b --python %s -- --export %s "
             "--out %s`. After the verdict write %s with {\"glb\": <approved poses>} (the variant's parameters copied into the "
             "motion file) and run again."
             % (n, ks, os.path.basename(BD["bvh"]), BD.get("pick", "auto"), samples_line(listed(BD["all"], R)), P,
                BD["merged"], ks, n, eb, script_path("pose_edit_scene.py"), eb, hg, appr))
    poses_glb = json.load(open(appr, encoding="utf-8"))["glb"]
    meta = poses_glb + ".json"   # written by pose_edit_scene.py --export: the sample the author posed on
    on = json.load(open(meta, encoding="utf-8")).get("sample") if os.path.exists(meta) else None
    if on and os.path.normcase(os.path.normpath(on)) != os.path.normcase(os.path.normpath(BD["bvh"])):
        stop("action '%s': the approved poses %s were set on %s, but the body sample is %s: Kimodo would get wrong deltas. "
             "Take that sample (--sample %s=N with %s deleted) or pose again on this one."
             % (n, poses_glb, os.path.basename(on), os.path.basename(BD["bvh"]), n, appr))
    # 5c. motion through the poses: every sample through the chain, best by audit -> review_page.py -> STOP for the verdict
    if not stage("ai", choice, motion, RIG_AI, appr):
        w = json.load(open(choice, encoding="utf-8"))
        if n in SAMPLE:
            (o, bvh, _), rows = by_hand(n, w["all"], R, "Kimodo-through-poses")
            name = os.path.splitext(os.path.basename(bvh))[0]; pd = os.path.join(D, "p")
            done = os.path.join(pd, "prop_%s.glb" % name)   # the audited file: after the prop solver or a recipe
            w.update(bvh=bvh, clip=os.path.join(pd, "clip_%s.glb" % name), score=o,
                     glb=done if os.path.exists(done) else os.path.join(pd, "merged_%s.glb" % name),
                     key_hands=os.path.join(pd, "keyhands_%s.json" % name),
                     audit=os.path.join(pd, "audit_" + name), all=[list(x) for x in rows], pick="by hand")
            json.dump(w, open(choice, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return verdict(n, w, D, with_prop)
    kf = os.path.join(D, "kf"); os.makedirs(kf, exist_ok=True); pj = os.path.join(kf, "poses.json")
    blender("keyposes_to_kimodo.py", "POSES OK", poses_glb, BD["merged"], BD["bvh"], pj, ",".join(map(str, fr)), n, *SK)
    if not os.path.exists(emb): python(script_path("kimodo_text.py"), "--motion", motion, "--out", emb, exe=KIMODO_PYTHON)
    python(script_path("kimodo_keyposes.py"), "--motion", motion, "--emb", emb, "--base", "%s:%d" % (os.path.join(e1, "body.npz"), BD["idx"]),
           "--poses", pj, "--keys", keys(R, fr, lp), "--out", kf, "--name", "kf", "--samples", count, "--seed", seed, exe=KIMODO_PYTHON)
    (score, bvh, glb, _), scores = best_of(sorted(glob.glob(os.path.join(kf, "kf_s*.bvh"))), motion, with_prop, os.path.join(D, "p"), lp,
                                           (poses_glb, fr))
    name = os.path.splitext(os.path.basename(bvh))[0]
    out = {"bvh": bvh, "npz": os.path.join(kf, "kf.npz"), "clip": os.path.join(D, "p", "clip_%s.glb" % name), "glb": glb,
           "score": score, "audit": os.path.join(D, "p", "audit_" + name), "pose_frames": fr,
           "key_hands": os.path.join(D, "p", "keyhands_%s.json" % name),
           "all": [[o, b, m] for o, b, _, m in scores], "pick": "auto"}
    json.dump(out, open(choice, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return verdict(n, out, D, with_prop)


def verdict(n, w, D, with_prop):
    """The audit does not close a motion (an approved clip had audit FAIL 1.40) - the human verdict on the review page does."""
    pg = os.path.join(D, "review")
    python(script_path("review_page.py"), "--glb", w["glb"], "--action", n, "--out", pg, "--title", "%s %s" % (C["name"], n),
           "--hand-frames", ",".join(map(str, w["pose_frames"])), *(["--prop", PROP] if with_prop else []),
           *(["--key-hands", w["key_hands"]] if w.get("key_hands") and os.path.exists(w["key_hands"]) else []),
           *([] if C["actions"][n].get("loop", True) else ["--no-loop"]), *SK,
           *(["--under-arm"] if with_prop and "butt_push" in json.load(open(r(C["actions"][n]["ai"]), encoding="utf-8")).get("aim", {}) else []))
    stop("action '%s': sample %s (%s), score %.2f (score / hands moved: %s). Review page: %s. Another sample: --sample %s=N. "
         "After approval set actions.%s.approved = {\"bvh\": \"%s\", \"score\": %.2f, \"key_hands\": true, \"date\": \"YYYY-MM-DD\"} in character.json "
         "and keep the BVH and %s." % (n, os.path.basename(w["bvh"]), w.get("pick", "auto"), w["score"],
                                       samples_line([(x[0], x[1], x[2] if len(x) > 2 else None) for x in w["all"]]),
                                       os.path.join(pg, "page.html"), n, n, w["bvh"].replace("\\", "/"), w["score"], w["npz"]))


CHOICE = {n: ai_action(n, a) for n, a in AI_ACTIONS.items()} if end >= STAGES.index("ai") else {}

# 6. merge all actions, prop in hands per action, audit of every action
if (CHOICE or LIB_ACTIONS or PROP_MOTION) and end >= STAGES.index("merge") and stage("merge", READY, RIG_AI, *[w["clip"] for w in CHOICE.values()],
                                                                     *PROP_MOTION.values(), *RECIPE.values()):
    merge(RIG_AI, LIB_ACTIONS + [(n, w["clip"]) for n, w in CHOICE.items()], MERGED, SKEL)
    # every action from the same MERGED, not chained: an export reorders vertices and the grip depends on it (combine_actions.py)
    after = {}
    for n, motion in PROP_MOTION.items():
        after[n] = os.path.join(WORK, "%s_after_%s.glb" % (C["name"], n))
        blender("prop_in_hands.py", "OK ", "--glb", MERGED, "--rig-data", RIG_DATA, "--motion", motion, "--out", after[n], *SK)
    cur = os.path.join(WORK, "%s_with_prop.glb" % C["name"])
    # always, also without a prop: combine_actions puts every action on the walk's ground (a Kimodo clip stood 0.5 m lower)
    if GROUND != "walk": print("== merge: no 'walk' action, grounding on '%s'" % (GROUND or "nothing"))
    steps = [os.path.join(WORK, "%s_before_%s.glb" % (C["name"], n)) for n in RECIPE] + [cur]
    blender("combine_actions.py", "COMBINE OK", "--base", MERGED, *("--action=%s=%s" % kv for kv in after.items()),
            "--ground=" + GROUND, "--out", steps[0])
    # one after another on the same file: a recipe keys its own action and may add its object once (nothing sampled by vertex index)
    measured = {}   # each recipe's report lies next to the file it wrote
    for (n, motion), src, dst in zip(RECIPE.items(), steps, steps[1:]):
        run_recipe(json.load(open(motion, encoding="utf-8"))["recipe"], src, motion, dst, SKEL); measured[n] = dst.replace(".glb", "_recipe.json")
    report = {}
    for n in C["actions"]:
        report[n] = audit(cur, n, os.path.join(WORK, "audit_" + n), PROP, rest_is_normal=n not in PROP_MOTION,
                          loop=C["actions"][n].get("loop", True), skeleton=SKEL,   # "loop": false for a one-shot action (death)
                          recipe_report=measured.get(n),
                          under_arm=n in PROP_MOTION and "butt_push" in json.load(open(PROP_MOTION[n], encoding="utf-8")).get("aim", {}))
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
