# ai-motion-to-sprites

[![CI](https://github.com/matzssue/ai-motion-to-sprites/actions/workflows/ci.yml/badge.svg)](https://github.com/matzssue/ai-motion-to-sprites/actions/workflows/ci.yml)

Text-to-motion for 2D games. One command takes a generated 3D character to an animated, audited GLB ready for
8-direction sprite rendering. Along the way it plans motion from sentences with [NVIDIA Kimodo](https://github.com/nv-tlabs/kimodo),
retargets it to a rig with Mixamo-compatible bone naming, puts a two-handed prop (a crossbow, a staff) into the hands with finger wrapping,
and checks every quarter frame for problems a human would reject.

It was built for a real game: an isometric action roguelite with a few hundred enemy animations. In production, the AI motion
part was easy. The hard part was knowing which takes are broken before a person spends time looking at them.

```
model.glb ─► prepare ─► auto-rig ─► AI rig ─► calibration ─► Kimodo (text + key poses) ─► retarget ─► prop in hands ─► audit ─► 8-dir preview
                                       │                          ▲                                                        │
                                       └─ STOP: review rig        └──────── STOP: review key poses ───── STOP: review motion ┘
```

## What it does

| Stage | Script | What happens |
|---|---|---|
| prepare | `prepare_for_rigging.py` | weld UV seams, decimate to ~25k tris, shrink and embed the texture; a separate prop mesh (`prop_model`) joins marked, so joint detection and weights see the body alone |
| rig | `auto_rig.py` + `auto_rig_blender.py`, `hand_fingers.py` | silhouette-based joint detection (crotch, armpits, fingertips, robe/hunchback cases); the tool's own skeleton (`skeletons/amts.json`: 3-bone spine, 5 fingers x 3 bones per hand placed on the hand mesh, fist self-check of the finger skinning) or, with `--template`, a skeleton with Mixamo-compatible `mixamorig:*` names whose hierarchy, rest orientations and finger bones come from the Mixamo-skeleton FBX you supply; voxel-proxy bone-heat weights; a symmetry gate stops a rig whose mirrored joints disagree (one side found on a prop). Benchmarked against 18 rigs made by Mixamo (`--bench`) |
| rig_ai | `prepare_rig.py` | cuts the prop out of the mesh (or takes a separate prop mesh whole) onto its own bone (rule-based selection, island closure, thin-part growth for bow strings, debris cleanup), grows finger bones out of fused claws (keeps the rig's own fingers when it has them), finds the thumb and the palm side |
| calibration | `merge_actions.py` + `motion_audit.py` | library clips must pass the audit on this rig, so a bad rig is not blamed on the AI motion |
| ai | `kimodo_text.py`, `kimodo_motion.py`, `kimodo_keyposes.py`, `keyposes_to_kimodo.py` | one sentence per phase; body samples without hand constraints; key poses set on the best sample and reviewed; then Kimodo is constrained through those poses (`FullBodyConstraintSet`) |
| (chain) | `soma_to_mixamo.py`, `prop_in_hands.py` | SOMA77 BVH to the rig, bone by role (skeleton profile), with an A/T rest-pose correction and loop closure; prop pose search without body collisions, analytic two-arm IK, Viterbi path for grip roll and elbow over the whole clip, fingers wrapped on the real prop surface (BVH), recoil |
| merge | `combine_actions.py` | every action processed from the same merged file, then combined and grounded on the walk |
| preview | `preview_8.py`, `review_page.py` | 8 isometric directions; a self-contained review page with a frame-synced player, hand close-ups and audit numbers next to the previous version |

```
pipeline/
  character.py, chain.py, variants.py   orchestration: whole character, one sample, parameter grid
  lib/       config (env paths), GPU queue, skeleton profiles, body collisions, skin-twist math, audit metrics, Kimodo setup
  rig/       prepare, auto-rig, AI rig
  motion/    Kimodo, retarget, prop in hands, merge/combine actions
  checks/    motion audit, skin check, alpha check, motion compare
  review/    8-direction preview, hand close-ups, review page
```

`character.py` runs all of it from one `character.json` (see `examples/`). It skips stages whose outputs are newer than their
inputs, and stops with an exit code of 2 at each human gate.

## Quality gates

`motion_audit.py` deforms the mesh every 1/4 frame and measures:

| Group | Metrics | Limit (for a 1.8 m character, scaled by height) |
|---|---|---|
| penetration | prop / hands / forearms in head, torso, legs, clavicles; fingers in prop; fingers in head (reported only) | 0.5 cm (head) to 4.5 cm (forearm in torso) |
| joints | wrist bend and twist, mesh stretch (a bad weight makes a "stick"), **arm skin twist** | 85°, 60°, 30 cm, 120° / 0.5 |
| smoothness | elbow, hand, finger, head, prop jumps; loop seam | 3 cm, 8°, 6°, 4°, 10 cm; 15° / 12 cm |
| grip | gap between each palm and the prop | 3 cm |

"Inside" is decided by a 10-ray vote against the arm-less body volume. The sign of the nearest face alone gave 10 cm
false positives next to open cloth sheets. On failure the audit renders close-ups from 5 sides at the deepest point.
The `score` (sum of max/limit − 1) only ranks Kimodo samples. Approval stays with a person: one approved clip still
scored FAIL 1.40.

### Choosing a sample

A clean audit also rewards a sample that did nothing: hands held still cannot go through anything. So `character.py`
also measures how far the hands moved in each raw Kimodo sample (`pipeline/lib/bvh.py`: the larger hand's extent
against the hips over the clip) and takes the lowest score only among the samples that moved at least 40% as much as the
most active one in the batch (`stages.ACTIVE_SHARE`). Both numbers are printed for every sample, in the STOP messages and
in the review service. Measured (share of the batch's most active sample):

| batch | samples that stood still or held the hands at the head | approved / chosen by a person |
|---|---|---|
| Padlinozerca attack, round 1 | s0 0.31 (audit 1.18, hands at the head all clip), s2 0.18 | s1 1.00 (the only real claw rake, audit 17.31) |
| Wybuchacz run, body | s0 0.18, s2 0.23 (audit 0.00) | s1 1.00 |
| Wybuchacz attack and run, through the key poses | none | attack s1 0.89, run s0 0.50 |

A cut between 0.31 and 0.50 separates them, so the cut is 0.4. It does not catch a whole batch that missed the phases.
In Padlinozerca round 2 no sample did the swipe: 0.72-1.00, and s0, with the claws held at the head, still wins the tie at
1.18. To take another sample:
`python pipeline/character.py --character <c>.json --sample attack=2` (or the "Sample of attack" choice in the review
service's run panel). Before the key poses are approved it picks a body sample, after that a sample made through the poses. A metric that needs a part the skeleton does not have (fingers, clavicles: `absent` in its profile) is
listed in `skipped` with the reason and left out of the score.

### Skin twist (`skin.py`, `skin_check.py`)
Bone-twist angles did **not** separate good clips from bad ones. An approved overhead strike had a 136° elbow/wrist
twist, more than a rejected swing. Cross-section collapse, triangle shear and LBS-vs-DQS difference did not separate
them either. What a viewer sees as a "candy wrapper" is skin stripes along the arm turning into a spiral. So the
metric takes every vertex's angle around the upper-arm/forearm axis, carried from rest by the torso rotation, and
fits a circular regression `angle = a + twist·t`:

- `skin_twist`: degrees per segment length; `skin_spread` = 1 − coherence;
- rejected swings: 210–260°, spread 0.45–0.80; approved clips: ≤ 60°, ≤ 0.41.

`skin_check.py` also works on poses produced by any script (procedural IK, hand-posed keys) via `--script/--pose-expr`.
It renders the worst frame with stripes that spiral when the skin is twisted.

### Alpha (`alpha_check.py`)
When a sprite frame is composited with a holdout mask (water, a bridge), the mask can cut through the middle of
a finger, so the tips float. The check labels blobs of the raw body layer and counts visible pieces detached from their blob.
Mask-edge specks are 2–19 px and cut fingertips 65–374 px, so the limits are 30 px per island and 100 px per frame.

### Other tools
- `compare_motion.py`: frame-by-frame bone diff of two GLBs. After a *tool* change the approved motion must come out
  `IDENTICAL` (0.5 mm / 0.5°). The audit score alone has ±0.1 noise from GLB vertex reordering.
- `variants.py`: cartesian grid (or named set) of motion-file parameters, run in parallel within free RAM, ranked table
  with per-group scores and `LIMIT` lines (a solution stuck at the edge of its search range).
- `gpu_queue.py`: one 8 GB GPU shared by Kimodo (which allocates 14 GB and spills to RAM) and Eevee renders. It uses a PID lock
  file and waits while a foreign process holds the GPU. A render next to Kimodo took 28 min instead of 2.

## Results from production

Measured on the game's characters (assets are not included):

- Crossbow shot on a hunched crossbowman: a version with hand constraints in Kimodo scored 3.8–17.8, with a hand in the head
  in every sample. Without hand constraints the score was 1.9–3.3. With reviewed key poses: **1.40, approved after one round**
  (v10 before key poses: 7.29).
- Sample spread for the same text is larger than any parameter tuning (1.4 / 4.4 / 4.5 / 15.9), so every sample runs
  through the full chain and the best one is picked by audit.
- Grip chosen frame by frame jumped 60° (hand) and 95° (fingers) between frames. A Viterbi path over the clip plus finger
  smoothing removed the jumps. Smoothing whole arms broke the grip (score 10.4 → 21.7).
- A Kimodo clip stood 0.5 m lower than the library walk, so in game the sprite jumped ~35 px on every clip change.
  `combine_actions.py` grounds every action on the walk.

## Limitations

- **Bipedal humanoids only.** The auto-rig expects an A/T pose facing −Y with two arms and two legs, and Kimodo generates
  human motion. Quadrupeds, spiders, snakes and other body plans are not supported.
- **Bone names come from a skeleton profile.** Every stage after rigging finds bones by role (`skeletons/*.json`). Built
  in: `amts` (the tool's own skeleton, what the auto-rig builds without a template), `mixamo` (built from a Mixamo
  template; the default when `character.json` has a template or a library walk) and `soma` (Kimodo's output). A Wybuchacz
  and a Kusznik rig with every bone renamed to the SOMA convention audit identically to the Mixamo originals. Still
  fixed: the spine must have as many bones as SOMA's (3), library clips must be on the Mixamo skeleton (they cannot go
  onto `amts`: clips are copied as armature-space poses, which needs the same rest frames), and `prepare_rig.py` reads
  the auto-rig's joints file. Fingers, toes, clavicles and bone tips may be declared absent; missing arms or legs are not
  supported.
- **No foot IK.** Retarget copies rotations and scales the root motion by leg length. A character whose proportions are
  far from human can slide or float its feet, and the audit has no foot-contact metric yet.
- **One prop, held in both hands**, with a stock-like long axis (crossbow, bow, staff). One-handed props (sword, shield,
  torch) are not supported.
- **Fingers: the prop grip, or Kimodo's hand pose.** The own skeleton places 5 fingers per hand from the mesh (claws or
  fingers found on it; a mitten or fused claws get 5 chains spread evenly) and takes the finger bends of Kimodo's hands
  (a fixed relaxed curl) outside a grip; on a Mixamo-template rig finger bones are grown out of fused claws with
  per-character thresholds measured by hand and Kimodo's finger motion is dropped. Hands holding something without a prop
  (straps, a keg) are not posed yet.
- **No sprite sheets yet.** The repo ends at an audited GLB and an 8-direction preview. Rendering the sheets is left to
  your own renderer.
- **No runnable demo.** `examples/` describe a character whose assets are not included, and the first run needs Kimodo
  plus the gated Llama 3 encoder (~20 GB).
- **Windows only so far.** Paths are handled for Linux and macOS, but nothing was run there.
- **Commercial-use checkpoints only.** `KIMODO_MODEL` must be a `Kimodo-SOMA-*` or `Kimodo-G1-*` checkpoint (NVIDIA Open
  Model License). Every script refuses `Kimodo-SMPLX-RP-v1` (NVIDIA R&D Model License) and any name not on the allowlist.

## Setup

- **Blender 4.4+** (actions with layers/slots). Set `BLENDER` to its executable, or put `blender` on `PATH`.
- **Kimodo** in its own venv (Python 3.10, CUDA). `KIMODO_DIR` (default `~/kimodo`) should contain `venv/`, `repo/` and `hf/`:
  1. clone [Kimodo](https://github.com/nv-tlabs/kimodo) into `$KIMODO_DIR/repo` and install it into `$KIMODO_DIR/venv`
     following its own instructions (torch with CUDA);
  2. into the same venv: `pip install transformers peft bitsandbytes` (`kimodo_text.py` loads the 4-bit Llama encoder itself);
  3. Meta-Llama-3-8B-Instruct is gated: request access on Hugging Face yourself and log in with `HF_HOME=$KIMODO_DIR/hf`.
     Weights land in `hf/`, about 20 GB in total.
  Optional: `KIMODO_PYTHON` (another interpreter) and `KIMODO_MODEL` (default `Kimodo-SOMA-RP-v1.1`).
  The GPU queue (`gpu_queue.py`) keeps its lock in `KIMODO_DIR` (the temp dir without Kimodo); `AMTS_GPU_QUEUE=0` turns it off,
  `AMTS_GPU_THRESHOLD_MB` (default 2500) is the GPU memory in use above which a Kimodo script waits.
- Host Python with `numpy`, `scipy`, `Pillow`, `jsonschema` (auto-rig, alpha check, review page, config validation, tests):
  `pip install -e .`
- Optional: a Mixamo-skeleton FBX (any library clip), only for a `mixamorig:*` rig (`auto_rig_template`, or the library
  walk) and for library clips (calibration walk). Download it yourself from Mixamo. Clips are not redistributed here, and Mixamo
  output must not be used to train or test ML/AI systems (LICENSES.md).
  Without one the auto-rig builds the tool's own skeleton.

The files in `examples/` describe a real character whose assets are not in this repo: copy them next to your own model
and clips, fix the paths, and measure the coordinates in `rig.example.json` on your model. `schemas/` describes every key;
`character.py`, `chain.py` and `variants.py` check the configs against it before any Blender step.
A rig that is not Mixamo-named needs a skeleton profile: copy `skeletons/mixamo.json`, map each role to your bone, list the
parts the rig lacks in `absent`, and set `"skeleton": "my_rig.json"` (or a built-in name) in `character.json`. Blender
scripts take it as `--skeleton`. Without it every stage uses `mixamo`, and optional bones the rig lacks count as absent.
The own skeleton (`amts`, [pipeline/lib/own_skeleton.py](pipeline/lib/own_skeleton.py)): Blender-style names (`hips`,
`spine.1`-`.3`, `neck`, `head`, `shoulder.L`, `upper_arm.L`, `forearm.L`, `hand.L`, `thumb.1.L`-`pinky.3.L`, `thigh.L`,
`shin.L`, `foot.L`, `toe.L`, and non-deforming `*_end` leaves); rest orientation: every bone's Y axis runs to the next
joint, Z points to the character's front (-Y), or up for feet and toes, or to the palm for hands and fingers, so a
positive rotation about a finger's X curls it into the palm (the palm side comes from the index and pinky knuckles, and
`prepare_rig.py` takes the grip's palm normal from the same knuckles). Its profile lists the finger chains
(`finger_chains`), so the retarget carries Kimodo's finger bends onto them. The spine split, the clavicle start and the finger joints
use SOMA77 proportions; nothing is read from a Mixamo file.
Then:

```bash
python pipeline/character.py --character my_character/character.json
blender -b --python pipeline/checks/motion_audit.py -- --glb out.glb --action attack --prop crossbow --out audit/
blender -b --python pipeline/checks/skin_check.py -- --glb out.glb --action attack --out skin/
python -m pytest                        # see "Development"; every test file also runs alone: python tests/test_skin.py
```

Every script prints its usage with `--help`. Blender scripts take their arguments after `--`.

### Motion file in words
The prop frame has +Y on the character's *left*, which makes sign mistakes easy. So a grip can be written in words:

```json
"right": {"x": 0.08, "palm": "from below", "fingers": "left", "fingers_tilt": ["forward", 45]}
```

Every run prints the grip back in words (`grip right: palm from below, fingers left and 45 deg forward, 33 cm in front of the butt`).

## Development

Host Python 3.10+, no Blender or Kimodo needed:

```bash
pip install -e ".[dev,server]"   # numpy, scipy, Pillow, jsonschema + pytest, ruff, pip-licenses; FastAPI, uvicorn
python -m pytest            # auto-rig, grip words, stage helpers, config schemas, skin and alpha checks, review service
ruff check .                # pyflakes and syntax errors only; the dense style is deliberate
```

CI runs the same on Ubuntu and Windows (and lint, typecheck, tests and build of `web/` on Ubuntu), plus a license scan of the runtime dependencies (GPL, AGPL and non-commercial
licenses fail; see [LICENSES.md](LICENSES.md)). `AMTS_EXTRA_CONFIGS="<glob>;<glob>"` makes the schema test also check
your own `character.json`, rig and motion files.

## Web viewer

[`web/`](web/) is a browser viewer for one audited motion (Next.js, React, react-three-fiber). Drop the GLB the audit
ran on plus `audit.json` (and `audit_samples.json`) onto the page: it plays the clip in 3D with the 8 game directions,
draws every metric over time against its limit, and clicking a failure jumps to that frame with a marker on the audit
point. Files are read in the browser, so the static build needs no server. Setup, data flow and the Blender to three.js
coordinate and frame conversions (with the measurements behind them) are in [web/README.md](web/README.md).

## Review service

[`server/`](server/) is a local FastAPI service over `character.py` for the human gates. A reviewer opens a character,
sees every stage (up to date, runs next, waiting for review, not reached) and what the waiting gate needs, watches the
motion in the web viewer next to its audit, and approves or rejects it: the service writes exactly what the STOP
message asks for (`poses_approved.json`, `actions.<action>.approved`), shows the change before writing, and keeps a
trail of every verdict. It can also start a run, stream its log and cancel it. It binds to 127.0.0.1 and only runs
the command it was started with, for the characters it was started with.

```bash
pip install -e ".[server]"
cd web && npm ci && npm run local -- <character.json or folder> --fake   # service + web; drop --fake for real runs
```

Open `http://127.0.0.1:3000/characters/` (the web app binds to 127.0.0.1 too). Endpoints, configuration and the safety rules: [server/README.md](server/README.md).

## Known traps (each cost a version)

- Kimodo hand targets assume human proportions. A hunched character gets hands in the head already in the raw motion,
  so the grip is solved afterwards and Kimodo only shapes the body.
- One long sentence gives a static pose for the whole clip. Write one sentence per phase. Every `multi_prompt` phase needs a
  constrained frame, or Kimodo fails on a reshape.
- Kimodo cannot do a deep forward bend from text ("chest on knees" twice gave a squat). Pose it by hand and generate through it.
- Bone lengths from GLB are meaningless, so Blender IK does not work there. IK is computed from bone heads.
- Bones without curves in an action keep the pose from another action in the file. Every script resets the pose after
  choosing an action.
- Success of a Blender step is its own marker line (`RETARGET OK`, `AUDIT`…), not the absence of a Traceback: some
  add-ons print one on every exit.

## Licenses

This repository: MIT. It contains **no** models, clips or weights. Every dependency and model it calls, with its license
and whether it allows commercial use, is listed in [LICENSES.md](LICENSES.md).

Mixamo is a trademark of Adobe. This project is not affiliated with or endorsed by Adobe; "Mixamo-compatible" refers
to bone naming only.
