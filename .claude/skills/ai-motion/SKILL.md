---
name: ai-motion
description: Full path of a character from a 3D model to audited animations (pipeline/character.py) and AI motion (Kimodo, text-to-motion) with a two-handed prop - prop rig (`rig_ai`), one sentence per motion phase, retarget by bone role, crossbow/bow/staff in both hands with fingers, penetration audit every 1/4 frame, skin-twist and alpha checks. Use ALWAYS when the task touches pipeline/, a character.json / rig config / motion file, Kimodo, "AI animation", "motion from text", a prop held in the hands, or when someone says "goes through the body", "hands in the head", "fingers wrong", "unnatural hands", "candy-wrapper arm". Contains the gates without which an early crossbow version went to review with the crossbow in the head.
---

# AI motion with a prop in the hands

Kimodo gives a better body (phases, weight, recoil) than hand keys, but it cannot do hands for non-human proportions
or a prop. The prop, grip and fingers are done by this repo's code, and **the audit checks every 1/4 frame**.
Show a take to a person only after the gates (§4).

## 0. Whole path: from model to every animation
One command per character, driven by `character.json` (see `examples/character.example.json`): model, rig, AI rig config,
work dir, output, actions (`library` = FBX clip, `ai` = motion file, `motion` = grip file for a library clip).
```
python pipeline/character.py --character <dir>/character.json [--from stage] [--to stage]
```
| stage | what | gate |
|---|---|---|
| (before) | the model: A/T pose, facing −Y | |
| prepare | `prepare_for_rigging.py` (decimate, embed texture; `prop_model` joins a separate prop, marked) | |
| rig | `auto_rig.py` (own skeleton `amts`; `--template <mixamo.fbx>` = `mixamorig:*`) | `auto_rig: symmetry` (STOP past the limit, AUDIT.md "Rig symmetry"); `auto_rig: fist` lines: share of hand edges torn on a fist |
| rig_ai | `prepare_rig.py` + preview | **STOP**: look at the preview (§2) |
| calibration | library actions on the AI rig + audit | FAIL = STOP, the rig or the measure is wrong, not the AI |
| ai | §3: body (4 samples, full chain) → key poses → Kimodo through the poses → 4 samples → best → `review_page.py` | **STOP** on poses (`<work>/<action>/poses_approved.json` `{"glb"}`) and on the motion (`actions.<a>.approved` `{"bvh","score","key_hands":true,"date"}`) |
| merge | every action in one GLB, prop in hands, audit of each | FAIL = STOP (approved action: worse than at the verdict) |
| preview | `preview_8.py`: 8 directions × 8 frames per action into `output` | review (§4) |

Bones after the rig stage are found by role through a skeleton profile (`skeletons/<name>.json`, schema
`schemas/skeleton.schema.json`): `character.json` `"skeleton"` (built-in name or path), every Blender script `--skeleton`.
No key = `mixamo` when the config has `auto_rig_template` or a library walk, else `amts` (the own skeleton the auto-rig
builds then); optional bones the rig lacks count as absent (configs from before profiles run unchanged). Library clips
cannot go onto `amts` (`character.py` refuses): base motions for it come from Kimodo.
Exit code 2 = a human gate. Finished stages are skipped (output newer than inputs). A run is long (Kimodo + several
samples at ~1.5 min each: prop 34 s, audit 31 s, retarget and merge): run it as a detached process, not inside a tool call
with a timeout.

## 1. Once per machine: Kimodo
- `KIMODO_DIR` (default `~/kimodo`): `venv` (Python 3.10, torch + CUDA), `repo` (Kimodo source), `hf` (HF_HOME: weights,
  Llama). ~20 GB, put it on a drive with room. Kimodo runs without its C++ module (MotionCorrection needs a compiler).
- **One GPU (8 GB) shared by several jobs:** `kimodo_*.py` wait in a queue (`gpu_queue.py`: lock `KIMODO_DIR/gpu.lock` with
  a PID + GPU memory over 2.5 GB without the lock). Eevee renders (`preview_8`, `hand_closeups`, audit close-ups, rig preview)
  take the same lock: Kimodo allocates 14 GB on an 8 GB card, a render next to it took 28 min instead of 2. Your own render
  outside these scripts starts with `gpu_queue.acquire(who, None)`. At most 2 Blender processes at once (`variants.py --parallel 2`)
  on a machine with little RAM: numpy fails with MemoryError, not with a clear message.
- Meta-Llama-3-8B-Instruct is gated: the user requests access on Hugging Face and puts the token into `KIMODO_DIR/hf/token`
  themselves. **Never read the token and never accept it in chat.**
- Licenses: README "Licenses". Never commit models, clips, weights or renders (`.gitignore`).

## 2. Once per character: the AI rig
Config `rig.json` (see `examples/rig.example.json`): prop vertex selection rules (tube/segment/box, `exclude`), prop frame,
growth over thin parts (bow strings), debris, claw thresholds.
```
blender -b --python pipeline/rig/prepare_rig.py -- --rig <rig>.fbx --config rig.json --out <work>/rig_ai.glb --preview
```
Check `*_preview_*.png` (open the full image, not a thumbnail):
- the prop is ALL red, including string ends; nothing of the body is red;
- `*_preview_hand_*`: 5 fingers in colours, **thumb red** and it really is the thumb (guessed as the most forward finger;
  wrong → `"thumb": {"Right": k}` in the config).

Calibration: the library walk on this rig must pass the audit (`character.py --from calibration --to calibration`, or by hand
`merge_actions.py` of the library clips onto `rig_ai.glb` + `motion_audit.py --prop <prop> --rest-is-normal` per action).
If it fails, understand why first (§5), then do motion.

## 3. Per motion (the blocks `character.py` calls; by hand only to fix one sample)
**Reference first, then the motion file.** A crossbow shot made without one needed the reviewer to point out what any
shooting manual says (left hand under the stock, elbow down, cheek to the stock). Before the first version: 2–3 sources on
the stance, conclusions in one sentence in the motion file's `_reference`, and grip vectors, elbows and head from them.
Motion file (see `examples/motion.example.json`): `phases` (duration + **one sentence per phase**), hand windows, `grip`
(per hand: `roll_deg` – how far the grip may rotate around the stock, `elbow_target` – where the elbow goes while aiming,
`knuckles_at_edge` – knuckles on the stock edge when fingers cannot reach its side), `aim` (`head_back_deg` – neck back,
`head_gaze` – how much the head comes forward to keep the eyes on target, `butt_from_shoulder` – where the butt goes,
`butt_push` – the world direction it leaves the body along, default forward; `[-1, 0, 0]` = to the right, for a stock under
the right armpit), `recoil`, `loop_blend_s` (how many last seconds the retarget leads back to frame 0).

**Write the grip in the character's words**, not vectors (the prop frame has +Y to the character's LEFT – sign mistakes are easy):
`"palm": "from below" | "from above" | "from the right" | "from the left"`, `"fingers": "left" | "right" | "forward" …`,
`"fingers_tilt": ["forward", 18]`. `palm_normal`/`direction` vectors still work; every run prints the grip in words
(`grip right: palm from below, fingers left and 18 deg forward, 34 cm in front of the butt`) – read that line before the render.

### Order (the approved crossbow shot, one review round)
1. **Body without hand constraints:** `kimodo_motion.py` (4 samples), each through `chain.py`; take the best by audit
   among the samples whose hands moved (README "Choosing a sample"; a sample that held still scored 1.18 beside the real
   rake's 17.31). Another sample: `character.py --sample <action>=N`, never by editing `body.json`.
   Do NOT use hand constraints in Kimodo: they pull the arms into the head of a hunched character (measurement in §5).
2. **Key poses** (start, peak; end = start so it loops) on that sample: `variants.py --frames 0,44` tunes grip and head on
   the poses alone (~15 s per variant), then `preview_8.py --frames 0,44` + `hand_closeups.py`. A pose no variant fixes is
   set by hand: `poses_by_hand/edit_<sample>.blend` + `pose_edit_scene.py --export` (§5, "Kimodo hand targets").
   **The poses go to review before any motion is generated** (8 directions, previous version next to it, audit numbers).
3. **Motion through the poses:**
```
<kimodo python> pipeline/motion/kimodo_text.py --motion <motion>.json --out <work>/emb.pt
blender -b --python pipeline/motion/keyposes_to_kimodo.py -- <poses>.glb <work>/e1/p/merged_body_s<N>.glb <work>/e1/body_s<N>.bvh <work>/kf/poses.json 0,44 <action>
<kimodo python> pipeline/motion/kimodo_keyposes.py --motion <motion>.json --emb <work>/emb.pt --base <work>/e1/body.npz:<N>
    --poses <work>/kf/poses.json --keys 0:0,55:44,125:0 --out <work>/kf --name kf
```
   Check the poses without Kimodo: add `--dry-run <out>.npz` to `kimodo_keyposes.py` (CPU, no model, no GPU lock; `--emb`,
   `--out`, `--name` may be left out): it prints hips and the lowest foot joint per key (Kimodo ground = 0) and the
   constraint rows (knight, 8 keys: 240 positions; with `--hand-rotations` 16 hand rotations).
   `<work>` here = `character.py`'s `<work_dir>/<action>`. `merged_body_s<N>` = retarget of THE sample the poses were set on
   (another sample gives wrong deltas without any error).
   Keys: Kimodo frame (30 fps) : pose frame (24 fps); last key = first pose. A one-shot action (`"loop": false` in
   character.json, `loop_blend_s: 0`) ends on its last pose and the audit skips the seam.
4. **All 4 samples** through `chain.py` (same motion file as the poses), best by audit among those that moved
   (`--sample` overrides) → `review_page.py`. With a prop the same `--key-poses` are the prop solver's target: §5, "Approved key poses".
   Sample spread is large (1.4 / 4.4 / 4.5 / 15.9) – one sample is a lottery.

`chain.py` does retarget → merge with the walk → `prop_in_hands.py` → `motion_audit.py`. `character.py` runs these steps
itself (pose frames from the motion file's `key_poses`, Kimodo keys from them). The audit does not close a motion: the
approved shot has audit FAIL (1.40) – the reviewer's verdict closes it.

### Tuning grip and pose: variants, not single runs
```
python pipeline/variants.py --rig <work>/rig_ai.glb --motion <motion>.json --merged <work>/p/merged_x.glb --out <work>/w1 --set grip.right.x=0.06,0.08,0.10 --set hold.body_clearance=0.14,0.18 [--frames 10,45,56] [--reference approved.glb]
```
The cartesian product (or `--file` with named variants) runs in parallel; output `table.md` best first, with group scores,
the three worst metrics, the difference from the reference and `LIMIT` lines. Work order:
1. **Quick try** `--frames <hold>,<aim>,<shot>` (~15 s per variant, no path over time): drops grips that make no sense in any pose.
   Close-ups of these frames: `hand_closeups.py --frames`.
2. Full run only for the best 2–3.
3. **`LIMIT …`** in the output = the solution sits at the end of its range (`roll_deg`, `elbow_deg`, `max_offset`) for most
   of the clip. Then tune the range or the grip itself, not penalty weights (both grips at ±20° in ~70% of frames once).
4. After a TOOL change (not a motion change): `compare_motion.py --a <approved> --b <new>` must print `COMPARE IDENTICAL`.
   A difference = a change in look = the reviewer's decision, not yours.

## 4. Gates before a review (every one, in this order)
1. **Audit OK** (`<out>/audit.json`, limits and their meaning: [AUDIT.md](AUDIT.md)).
   "May slightly pass through" = depth below the region's limit, not "a bit over".
   Never raise a limit to make a take pass; raise it only from a measurement, with an entry in AUDIT.md.
   The audit also measures arm skin twist (`skin_twist`, `skin_spread`). **Poses computed outside the chain** (a pose
   script, IK, bone rotations) go through the skin check separately, and a frame composited with a mask through the alpha check:
   ```
   blender -b --python pipeline/checks/skin_check.py -- --script <anim.py> --pose-expr "pose(nr / 20)" --frames 130-170:2 --out <dir> -- <script args>
   blender -b --python pipeline/checks/skin_check.py -- --glb X.glb --action attack --out <dir>
   python pipeline/checks/alpha_check.py --raw <body layer>.png --final <composited layer>.png --out <dir>
   ```
   FAIL = look at `closeups/*_stripes.png` (stripes along the arm turn into a spiral) and `alpha_islands.png` (islands in red).
   Both checks exist because a reviewer asked "we have an animation tool, and it did not catch this?" – a swing with
   twisted arms and fingers cut by a mask.
2. **Close-ups** of every failure (`closeups/`, 5 sides) and, even when OK, 3 frames by hand: start, aim peak, shot.
   The audit does not see "unnatural": fingers wrapped the wrong way, elbow up, palm sideways to the stock. Read full frames,
   not crops.
3. **Review page** with one command (audit + 8 directions × every frame + hand close-ups + numbers next to the previous version):
   ```
   python pipeline/review/review_page.py --glb X.glb --action attack --prop crossbow --out <work>/review_vN --title "Crossbow shot" --hand-frames 10,45,56,85 [--previous <work>/review_vN-1] [--note "what changed"]
   ```
   Output: a self-contained `page.html`. ~4 min, run it as a detached process.

## 5. Traps (each one cost a version)
- **Kimodo hand targets assume a human** (~1.75 m, head above the shoulders). A hunched character with the head in front of
  the shoulders gets hands and prop in the head already in the raw motion (8 cm). So the grip is solved by `prop_in_hands`,
  and Kimodo constraints only shape the body.
  Without a prop it lands in the key poses: on a rig whose shoulders sit where they really are, "hands to the chest"
  hits the jaw (Wybuchacz crouch 16.2 -> 6.2 after moving the hands to the belly in the key poses and running Kimodo
  through them). When no sample did the motion (Padlinozerca: no rake in 8 samples), pose the key frames by hand in the
  scene the key-pose STOP leaves (`<action>/poses_by_hand/edit_<sample>.blend`), save, and run
  `pose_edit_scene.py --export`. Approve that `poses.glb`. Checked: a 40 deg right forearm bend at the rake frame reaches
  `keyposes_to_kimodo.py` as `RightForeArm` 40 deg, with every other bone at 0. The game repo's
  `wybuchacz/ruch_ai/fix_key_poses.py` set poses with a script; this route is for posing by hand.
- **A prop or pack in the body mesh pulls the auto-rig's joints onto it** (Wybuchacz's backpack: spine and head 15-30 cm
  back; Flisak's pole behind him: head top on its knob, shoulders 19 cm off; Kusznik's crossbow: left elbow 8 cm). Give it
  as its own mesh, in the model's frame where it rests on the body: `character.json` `prop_model` (rig.json `prop` then needs
  no `select`/`debris`). It stays out of joint detection and of the weight proxy. Keep a pack on the upper back only:
  below Spine the waist bends away from it (a hip-length keg floated off the back in a sprint).
- **Hand constraints in Kimodo hurt** (same grip): samples without them scored 1.9–3.3 with no hand in the head; with them
  3.8–17.8, a hand in the head in every one. The spread between samples is larger than the gain from tuning: first every
  sample through the full chain, then parameters. Use key poses instead (§3): 1.40 vs 7.29 before.
- **The grip depends on GLB vertex order** (the solver samples 260 prop points by index) and every export changes it. The same
  shot processed after the walk (through the chain) moved 2 cm and 3°; the same walk from another file scored 0.21 or 3.40.
  So `character.py` processes every action from the same merged file and joins them with `combine_actions.py`; tune variants
  on the same file that goes into `character.py` (`<work>/<name>_merged.glb`).
- Bones without curves in an action keep the pose from another action in the file: these scripts reset the pose after choosing
  an action. A sprite-sheet renderer outside this repo may not – in a GLB for sheets give every action keys on every bone.
- A two-handed prop in a library walk/idle: a motion file with `"no_aim": true` (without it the arm swing "aims"), and in
  `character.json` an action with `"prop": true, "motion": <file>`. The crossbow had to sit 6 cm higher than in the shot,
  otherwise it caught the thigh.
- One long sentence = a static pose for the whole clip. One sentence per phase.
- **Locomotion pinned in place comes out standing** (a Kimodo sprint: all 4 samples moved < 0.2 deg). Set `root_speed` (m/s)
  in the motion file: the root travels forward during generation and the travel is subtracted before saving (clip in place).
- **Key poses passed bone rotations only (until 2026-11):** a hand-set crouch reached Kimodo at standing hip height and
  floated 41 cm (Padlinozerca). `keyposes_to_kimodo.py` now writes `hips` (`keypose_root.py`): crouch 0.52 m, foot joint
  -3.1 cm. A `poses.json` from before prints WARNING: rerun `keyposes_to_kimodo.py`. Kimodo has no foot-contact input.
- **Between key poses the root used to face forward in place** (`Root2DConstraintSet` on every non-key frame: heading
  [1, 0], (x, z) = the track), while a key carries its own pelvis. Poses with the pelvis turned (knight round 7: -23 / +30
  deg) snapped there only on the key frame and fell back: yaw steps up to 16.5 deg per Kimodo frame, shins shaking 2.6-3.1
  cm (round 5, unturned poses: 0..3 deg, 0.9 cm). `kimodo_keyposes.py` now sends heading and (x, z) interpolated through
  the keys' own (monotone cubic, `keypose_root.root_between`) and `--dry-run` prints that path; keys facing forward on the
  track give the old payload bit for bit. Gate: `pelvis_shake` / `knee_shake` (5-frame residual, `shake.py`).
- **Kimodo keeps a key pose's joint POSITIONS, not the hands' ROTATION:** a full-body key constrains positions only and the
  clip comes from the rotation channel; the knight's sword hand hit its keys 2-8 cm close but turned 15-176 deg off (the
  retarget is faithful: same error before and after it). The working fix: `chain.py --key-poses` runs `key_hands.py` after
  the retarget: forearm roll + rest of the hand rotation per key (wrist bend capped at 80 deg), smoothstep between keys,
  joint positions unchanged. `kimodo_keyposes.py --hand-rotations` also sends the hands' rotation to Kimodo (its own
  end-effector channel): EXPERIMENTAL, off by default, until a generation run shows Kimodo honours it. Gate: `key_hand_rot_L/R` on the key frames
  (limit 50 deg: knight before 101-176, after 0-1, bend-capped key 6-48). Cost on the knight: hand_jump at the strike
  +0.4..+7 deg, skin_twist +10, scores +0.03..+1.9; a sample whose wrist already folds 167 deg (r3b s2) reads a 177 deg
  wrist twist there. With a prop the grip solver sets the hands: measured, not corrected or scored.
- **Kimodo cannot do a deep forward bend from text** ("curls forward, chest on knees" twice gave a squat with the shoulders
  22 cm BEHIND the hips). Set such a key pose by hand from a reference picture (bone directions + 2-bone IK from bone heads)
  and run the motion through it. Measure the lean (shoulder vs hip along the forward axis), do not judge from a thumbnail.
- Every `multi_prompt` phase needs at least one constrained frame (otherwise a reshape error).
- A hand template from the end of a sample carries its crouch; `rest` windows take the pose from frame 0.
  "Lowers back down" = puts it on the ground; write "holding it low with both hands".
- "The head pops in the first frames" = the loop seam (Kimodo ends in another pose than it starts). Measure frame 0 vs the
  last; `loop_blend_s` in the motion file. Rotating Head alone only tilts the head up – pulling it back is the Neck.
- The end of a Kimodo sequence collapses: `tail_padding` generates longer and cuts.
- A Kimodo clip stands at another height than the library walk (0.5 m lower once): in game the sprite jumps on every clip
  change and the audit does not see it. `combine_actions.py` grounds every action on the walk (`--ground`).
- The auto-rig stands in an A-pose: without the CORR rest correction in `soma_to_mixamo.py` the arms go sideways.
- `LeftLeg` is the upper leg in SOMA and the lower leg in Mixamo: never match bones by name across skeletons, only by role.
  Library clips are copied by role too (`merge_actions.py --skeleton`); without it, by name only (as before).
- Bone lengths from GLB are meaningless: Blender IK does not work; IK is computed from bone heads.
- GLB splits vertices on UV seams: count connectivity and islands after welding positions. A mesh where the prop is fused
  with the body is one island: select by rules, not by island.
- Before `separate` always `deselect_all` in edit mode (selection left over from import).
- An uncut prop on the back has forearm weights: the audit sees "forearm in torso".
- "Inside" by the sign of the nearest face alone fails next to open sheets (rags, belts): 10 cm false positives at rest.
  The audit votes with rays (`collisions.inside`).
- The palm side taken from claw curvature came out as the BACK of the hand (two versions with the crossbow on the back of the
  hand, fingers bent backwards): the sign now comes from the thumb (`prepare_rig.py`). In an A-pose the palm faces the body/down.
  On the own skeleton the palm comes from the index/pinky knuckles, like the hand bone's roll: the point-cloud estimate took
  the wrist cloth and came out 127/150° off on Kusznik (wrist bent 96°, fingers sticking up out of the crossbow).
- **The finger wrap of the own skeleton bends each bone about its own axis** (local X), carried by the bones above it. One
  axis from the hand's palm normal for all three bones degenerates once the first one bends ~90° and the rest of the finger
  stood up beside the stock.
- **Jumps**: choosing grip and elbow frame by frame flipped between almost equal solutions (hand 60°, fingers 95° between
  frames; the audit did not measure that then). A path over the whole clip (Viterbi) + smoothed fingers; smoothing whole
  arms breaks the grip. Audit: `hand_jump`, `finger_jump`, `elbow_jump` (AUDIT.md).
- A prop pose search without an offset limit lifted the crossbow 37 cm over the head to avoid collisions (`max_offset`).
  Check the prop height frame by frame, not only the audit.
- A stock is not a cylinder: fingers wrap on the prop surface (BVH), not on a radius. But a grip by the bow mount has the
  mount, limbs and string closer than the far side of the stock: the own skeleton's long fingers wrapped those (hooks
  8-12 cm off the stock axis). Own chains aim at the stock's faces only (`stock_radius_max`) and collide with the whole prop.
- The thumb lies opposite the fingers: wrapped both ways; the angle from the palm axis picked the middle finger.
- A prop fused with the body in the model (Kusznik's stock goes through the quiver) is cut out with matching open loops in
  both meshes: a see-through hole in the stock by the right hand and in the quiver. `prepare_rig.py` welds the seam-split
  vertices and fills only loops lying on the other mesh's open edges; on the prop the cap follows the stock (a flat cap
  ran through the stock and the grip lifted the thumb off it). The stock's surface inside the quiver never existed, and the
  prop axis from the config runs 1-3.4 cm off it: a cap on the axis bulged like a barrel, a fan from the centre was spiky
  (author: "the fill did not work"). The cap now fits circles to the intact stock on both sides of the cut, moves the rim
  (up to 5 cm off, on the quiver wall) onto that surface and fills the loop with a grid on it (CDT). `cap quality` fails
  the rig when over 10% of the cap's faces turn more than 60 deg from the stock's outward direction (old fan 46%, now 0%). The right thumb had lain IN that hole: tuning done on a broken
  prop does not hold once it is fixed (`thumb_along_stock` 0.05 -> 0.2).
- A finger's weight outside its tube went to the hand even when the vertex belongs to another finger's claw: Kusznik's right
  middle claw had a quarter of the ring finger's weight, it became hand weight and the curl pulled the claw tip 3.6 cm
  back, folded over itself. Stray weight on another finger's outer bone goes to that bone (audit `finger_tip_fold`).
- Cords hanging from a wrist wrap sit inside the finger tube of the thumb's/pinky's first bone: weighted to it, the grip
  pulled them 4 cm and they showed as strings across the crossbow. Thin mesh beside a finger's first bone goes to the hand.
- `aim.head_back_deg` turns the neck back and the head forward. Bone heat gave the own skeleton's neck a third of the
  throat and the 50 deg tuned on an earlier rig stretched it (amts throat edges p95 1.5-1.8 x rest). The auto-rig moves the neck's weight to the head by height above the neck
  joint; moved whole, the base of the neck turned with the head into the hand at the cheek (hands_in_head 0 -> 1.8 cm), and
  the rule by height leaves most of that stretch: set `head_back_deg` per character, 0 when the stock is not at the cheek.
- Bone heat leaves the chest, clavicle and forearm on the middle of the upper arm: the elbow bend flattened the biceps
  (-23% radius). The auto-rig gives the middle of the upper arm to the upper arm alone, close to
  its axis and below the shoulder (from 0.6 of the bone, fading in from 0.45): taken from 0.15 and 0.2 m out, it moved the
  shoulder mass with the arm and tore the shoulder (author: "the left shoulder disappeared"; audit `skin_tear` 10-14%,
  now 0.4% with the biceps still -10%).
- A stock under the armpit (`butt_push` sideways) leaves the torso only: out of the whole body it went through the upper
  arm and stopped 13 cm outside the shoulder joint. The arms are not in the collision volume, so the butt also sat 5 cm in
  the right upper arm (author: "through the shoulder instead of under it"): lower it (`aim.butt_from_shoulder` z) until
  the audit's `prop_in_upper_arms` (`--under-arm`) passes.
- `aim.rest_at`: where the prop's rear end rests while aiming, by roles - `shoulder` (default) or `armpit` (default when
  `butt_push` is given). In the armpit the PROP is the target: the rear end is pinned in the pocket of that frame's body
  (depths `POCKET_TRY` x the upper arm below the shoulder joint), the prop only turns about it (aim kept within
  `AIM_FREE` = 10 deg), may slide back through the pocket by `STOCK_SLIDE` and leave it by `POCKET_SLIP`, and both arms
  are fitted to it. On the own skeleton every candidate is scored on the REAL skin with the audit's own checks
  (`prop_in_body`, hands/forearms in head/torso, `pocket_gap`); the old proxies (a body volume open at the shoulders, arm
  capsules) missed 7.7 cm of stock in the front armpit fold and every try swung the crossbow 50-60 deg sideways. The arm
  solver moves the real upper arm/forearm skin rigidly with each setup (only skin weighted >= 0.9 to the bone) and keeps a
  grip `REACH_SLACK` = 4% short of a straight arm (the left hand reached 2.3 cm past it). Kusznik: the solver's best was
  3.9-5.1 cm in the skin; the author's hand-posed frame 44 (final, rig kus13) has 0.1 cm in the upper arm and 4.2 cm in the chest side
  (`spine.3`), with the stock through the pocket and the butt behind the back. The author accepted it.
  Why seven rounds failed and what the tool needs: [GRIP_LESSONS.md](GRIP_LESSONS.md).
- A key pose posed by hand (the author's): `prop_in_hands.py --frames 44 --keep-prop` keeps the prop and the body as the
  GLB has them and fits only the fingers of a hand whose palm lies on the stock (its arm and hand stay exactly as posed); a
  hand off the prop takes the motion's grip by IK. Refitted to the motion's grip, the author's hands moved 2-6 cm and
  turned 28-39 deg (left wrist twist 75 -> 101 deg).
- **The aim's frames** (`W_AIM`, in `<glb>_arms.json` for the audit's pocket checks): stock on the shoulder, from the
  right hand's height; under the armpit, from the motion file (`lib/prop_path.aim_window`: the `aim` key pose, the
  phases, the shot). The hand's height pinned Kusznik's stock on the recoil and left it at the hip on the aim frame.
- **Approved key poses** (`chain.py --key-poses/--key-frames` -> `prop_in_hands.py`, with `<poses>_arms.json`): each key pose's prop is carried onto
  every frame's body (hold: hips; aim: chest under the butt-side shoulder joint) and kept while it costs at most 12
  more than on its own key frame; else held as the neighbour holds it, else searched near it, other pockets last.
  Key frames take the approved arms. `APPROVED PLACE` lines report it (Kusznik's key frames: 0.0 cm, 0 deg off).
  Why and what each rule gave: GRIP_LESSONS.md, round 9.
- Working mode (author, round 8): the solver poses; only a failed pose goes to the author, and the author's correction is a
  bug report: compare it with the solver's output on the same body, find why the solver did not get there, and fix the
  solver or the audit until it reaches a comparable pose by itself. Kusznik's aim (frame 44), what the comparison found:
  the solver's own cost scored the author's pose worse (the stock resting in the pocket counted as "in the arm" in the
  arm solver and as a body hit in `prop_hits`: both now leave the stock's rear span to the pocket allowance); a palm normal
  tilted along the stock moved the grip along it (`grip()` offsets the palm across the axis only: the left palm was 20 cm
  off the stock); and the pinned search started only with the rear end at the side of the ribs, turned about that end, so
  a turn swung the stock's middle into the chest. The starts now cover the pocket depths (deepest first), 0-12 cm in front
  of the shoulder joint, the stock slid back 0-100% of `STOCK_SLIDE` and turned +-`AIM_FREE` about the pocket point;
  `prop_hits` and the arm's reach slack (500/m, soft) count in the prop's place. The author then found the stock in the
  elbow (elbow pressed to the body) on a pose the audit passed: the pocket allowance (audit and solver) now covers only
  the torso side and the upper arm's top `POCKET_ARM` = 30%, and the pinned search costs a butt-side elbow less than
  `ELBOW_OUT` = 0.6 of the upper arm out of the shoulder joint (300/m). Swung out after the prop was placed, the arm's
  fold pressed the stock deeper, so the elbow is chosen together with the prop. Solver alone (s12) vs the author: stock
  yaw -20 / -18 deg, butt 10.6 / 12.4 cm out, 14.2 / 13.9 cm back, 15.8 / 21.3 cm below the shoulder joint, pitched
  -4 / +9 deg (the motion's `aim.pitch_deg` is 4 down); right elbow 21 / 20 cm out; grips within 2 cm; audit 0.33
  (author's pose 3.2 cm fingers in the prop, solver 1.1 cm: `index.1.R`'s base, which a raised radius does not move).
  Details: [GRIP_LESSONS.md](GRIP_LESSONS.md).
- Face skew guard (`prop_in_hands`, any skeleton, measured): before the prop is placed, a head turned about its own axis
  against the top spine bone is turned back 2 deg at a time when the audit's `face_skew` is over its limit, down to half
  of it (limit 2.5 cm; m1 Mixamo: 2.2 cm, untouched). The own rig's face is bound partly to the chest (the neck bone
  carries no skin), so a turned head drags the jaw and mouth sideways. Run after the placement it moved skin under hands
  already placed (Kusznik's recoil: audit 9.5 cm hand in torso, the search had measured 1 cm). A stop at 40 deg left
  5.4 cm of skew on the recoil (Kimodo's head 53-63 deg off the chest); without it the skew passes and the guard takes
  back up to 62 deg there. **It removes head turn**: the solver prints `FACE GUARD: ... most N deg on fr. F`, the audit
  and the review page carry it (`face_guard` in `audit.json`). An action with an intended head turn (a look over the
  shoulder): `"face_guard": false` in the motion file's `grip`, and expect `face_skew` to fail on this rig.
- Own finger bones whose skin ends in the prop after the wrap get their skin radius raised by that depth and are wrapped
  again (the median radius missed the thick side of the thumb's metacarpal: Kusznik's left thumb base 2.9 -> 0.9 cm).
  Moving the palm out instead did not help (the hand met the bow mount) and lifted the fingertips 6.5 cm off.
- Auto-rig elbow and wrist depth: the middle of ALL vertices in a slab around the joint put Kusznik's left elbow 8 cm
  behind the arm (the crossbow on his back lay behind it): upper arm 27.9 vs 31.6 cm, the skin off the bone, the left
  knuckles 5.5 cm off the mirrored right ones (author: "the left arm is broken from the base"). Elbow and wrist now take
  the slab's layer in Y on the shoulder-wrist line / at the fingertips. A `<out>_joints.json` next to the rig is REUSED:
  delete it to detect again.
- Auto-rig wrist and knee come from the mesh (where the hand widens; the kneecap on the leg's side contour), SOMA's
  fractions only without them. SOMA's wrist at 0.746 of Arm -> fingertip landed in the palm of long-fingered Kusznik and
  Wybuchacz, and the stored clip then put the forearm 9-10 cm into the torso instead of the hand; the knee as a fraction
  of ankle -> Hips sat 7 cm under Kusznik's kneecap once Hips moved.
- Armour (a plate knight) broke both: the leg has several bulges (greave top, poleyn, cuisse) and a tabard hem acts as
  the crotch, so the knee landed mid-shin; the gauntlet's cuff is wider than the hand, so the wrist sat 4 cm inside it
  and `prepare_rig` found an empty palm. The knee now follows the leg's own run in a side raster and takes the apex of
  the bulge nearest SOMA's knee; the wrist takes the start of the neck after a cuff. `prepare_rig` stops early on an
  empty limb bone or palm, naming the joint to move.
- Bone heat gives a vertex the nearest bone it can SEE in a straight line, at any distance. The knight's tabard hem saw
  none of its own bones behind the leg plates, only the front half of `toe.L` poking out of the sabaton, and took it at
  0.85-1.0 from 46 cm away (a spike in front of the hips in every leg pose; hem edges x13-24). Arm and leg bones keep
  weight only within 3-4 x their own skin radius (`pipeline/lib/weight_reach.py`); what is taken comes from the mesh
  neighbours, so cloth follows what the cloth above it hangs from.
- Thumb = of the front digits, the one leaving the hand nearest the wrist. "Most forward" alone tied on the knight's right
  gauntlet (index finger and thumb stub 10.8 cm each): the thumb chain went into the index finger, the stub got no bone,
  and the index tip shared by two chains folded at any curl (`finger_tip_fold` 21-64%, 0% after).
- Auto-rig head: skin whose largest weight is the head carries no weight of a shoulder or anything below it. Bone heat
  gave Kusznik's forward-hanging face up to 0.15 of the right shoulder and the cheek 0.10 of the right upper arm, and the
  aim pulled the face to one side (author).
- An own finger bent joint by joint swings its straight rest into the stock and stops half bent (right middle finger
  straight, tip 8.7 cm off). The grip also tries the rest of the finger curling with each joint; audit `finger_tip_gap`. Kimodo's aim frame (stock to the cheek) lifts the right clavicle and
  leans the neck onto where the stock goes: the key pose takes both from the hold frame before `prop_in_hands --frames`.
- Judging from thumbnails let a crossbow in the head through. Audit numbers + full frames.
- **A character off the ground passed the audit** until it measured feet: Padlinozerca's key-pose crouch floated 41 cm
  and the copy grounded by script skated 63 cm on landing, both silent (score 5.38 for other reasons). `feet_above_ground`
  is measured against the clip's own lowest foot point, `foot_slide` without the walk's treadmill (AUDIT.md, feet rows).
  A foot hanging beside a planted one is reported only (a step or kick does it too). An intended jump fails
  `feet_above_ground`: raise it for that action with `--limits`.
- **Fix passes do not converge** (frames with a collision 38 → 76 → 83 → 81) and the result is the last pass, not the best;
  the audit score after 1–6 passes jumps (17.1 / 19.3 / 12.8 / 7.3 / 5.5 / 11.6; `grip.passes`, default 4). The IK cost
  (spheres around bones) barely agrees with the audit (IK reports a collision in 81 frames, the audit an error in 32; in 9
  frames the audit fails and IK sees nothing). Tune for the audit, never for the "frames with a collision" counter; a small
  parameter change can rearrange everything (8.7 → 12.2 after 4 cm).
- **The prop pose search is slow by its count, not by its geometry** (own skeleton / armpit: every candidate pose is
  scored on the real skin). An aim frame asks for ~490 candidates (108 starts + six descents), a hold frame for ~28.
  Kusznik (38k vertices, 56k faces): 105 ms per candidate, 54 ms of it Python lists rebuilt for one BVH (labelled faces
  picked again, 38k Vectors) while the tree itself builds in 7 ms; one sample took 1 h 46 min. Now 13 ms: faces picked
  once, trees on the vertices they use, one skin deform per candidate, arm setups / body hits / skin depths remembered
  per prop pose inside a frame's search, a candidate dropped once its cost so far cannot beat the best (every part of
  the cost is >= 0), a frame whose body did not change since the last pass keeps its answer. Measure before tuning:
  `time [s]:` and `time, search:` in the output.
- **A speed change to the solver must give the same file.** A float that differs in its last bit flips one `<` in the
  descent and a frame comes out elsewhere (as with any small parameter change, above). Check a frame set with
  `--frames` and the whole clip with `compare_motion.py` (`COMPARE IDENTICAL`) against the output of the old code on
  the same merged file. Traps met: the matrix product of a part of an array may round differently from the same rows
  of the whole array's product; two trees over a split face set break ties (a point nearest to a shared edge) in
  another order than one tree, and the face decides the region and the sign.
- The solver closes the loop only when the first frame is an approved key pose (`--key-poses`); without one the last and
  first frame can differ (7 versions had 30° on the seam). Audit: `loop_seam_*`.
- `prop_in_hands` ends with `PROP IN BODY` and `LIMBS IN BODY` on the placed pose; `--frames` prints each cost by part.
- Read the audit with `share` and `side` (AUDIT.md): "fr. 1–99" is a range, not the whole clip; "forearm in head" does not say which one.
- Blender add-ons may print a Traceback on exit: success of a step is its marker line (`RETARGET OK`, `OK`, `AUDIT`),
  not the absence of a Traceback.
