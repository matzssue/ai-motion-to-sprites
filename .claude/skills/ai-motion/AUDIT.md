# Motion audit: what it measures, limits, calibration

`pipeline/checks/motion_audit.py`: the deformed mesh every 1/4 frame (plus a rest sample), result in `audit.json` and
`audit_samples.json`; on failures, close-ups from 5 sides.

## Reading the result
- `errors[metric]`: `max`, `limit`, `at_frame`, **`share`** (fraction of samples over the limit), `side` (L/R), `area`.
  `range` is only the first and last bad sample: "fr. 1–99" with `share` 0.25 is NOT the whole clip
  (a wrist read as "96° for the whole clip" was over the limit in 25% of samples, only while holding low).
- `side`: which arm. Once the LEFT forearm and the RIGHT hand were in the head – without it the wrong arm got fixed.
- `score` = sum of (max/limit − 1), 0 = OK; it ranks samples. **`scores`** splits it into groups:
  `penetration`, `joints`, `smoothness`, `grip`, `feet`. Compare versions by group and metric, not the sum: a new metric changes the sum.
- `score_area` = the same averaged over samples: one bad frame does not dominate.
- `no_limit`: metrics for information (no bad sample to calibrate against yet) – read them, they do not decide OK.
- `skipped`: metric -> reason, for metrics whose skeleton roles are absent (`NEEDS` in `pipeline/lib/audit_metrics.py`);
  not measured, not in `maxima`, not scored. `skeleton`: the profile used.
- A new metric goes into `METRICS`, `NEEDS` and `LABELS` (`pipeline/lib/audit_metrics.py`), then
  `python pipeline/lib/audit_metrics.py --catalog web/src/audit/catalog.json`: both review pages take unit, group and
  label from there (`tests/test_audit_metrics.py` fails on a missing one; a fraction shown as "14.3 cm" happened once).

## How "inside" is decided
The body without arms (from the upper arm down) is one almost closed volume; every face has a region from weights
(head / torso / clavicles / legs). A point is inside when the nearest face points away from it (normal sign) **and**
≥8 of 10 rays hit a back face first. Depth = distance to the nearest face (up to 12 cm; "12.0" = at least 12).
Regions measured as separate volumes gave 15 cm false positives (they are open where they meet).

## Limits (m for a 1.8 m character, scaled by height; angles in deg; jumps per 1/4 frame)
Height (`height_m`) is the rig's rest pose, one number per rig (`audit_metrics.height`). Until 2026-11-20 it came from the
posed first frame of the action: Padlinozerca's 8 attack samples got 1.40-2.15 m against 1.90 m at rest, so a crouching
sample had limits up to 26% tighter. Scores of approved motions moved with that change; see the PR for the numbers.
| group | key | limit | meaning / calibration |
|---|---|---|---|
| penetration | prop_in_head, hands_in_head | 0.005 | nothing in the head: a reviewer sees it at once |
| | forearms_in_head | 0.01 | |
| | prop_in_torso / prop_in_legs | 0.015 | stock pressed to the shoulder, not in it |
| | prop_in_clavicles | 0.03 | a stock in the shoulder pocket is real contact |
| | prop_in_upper_arms | 0.015, only with `--under-arm` | the arms are not part of the body volume above (they move with the prop), so a stock butt under the armpit went 5.5 cm into the right upper arm unmeasured (author: "the crossbow goes through the shoulder"). The check uses its own upper-arm volume. Off by default: a stock on the shoulder sits in it by design (approved Mixamo shot 7.4 cm); `chain.py` / `character.py` pass `--under-arm` when the motion has `aim.butt_push` |
| | prop_in_body | 0.015 | ANY prop against the WHOLE skin, every region by skeleton role (head, torso, clavicles, legs, upper arms, forearms, hands, fingers; `_prop_in_body` = depth per region, e.g. `forearms.R`). The exemptions are the grip zone of each holding side (hand within 3 cm of the prop): its hand, fingers and the forearm within `GRIP_ZONE` = 0.25 of its length from the wrist, and on `--under-arm` aim frames the stock resting in the armpit pocket (`prop_in_pocket`). Kusznik r6: 3.1 cm `forearms.R` (author: "the weapon goes through the forearm"); the approved Mixamo shot fails it honestly: butt 7.4 cm in the right shoulder (`upper_arms.R`). The author's own hand-placed under-armpit pose: 4.4 cm (torso) / 3.4 cm (upper arm). `prop_in_hands` measures the same volume |
| | rest_gap | 0.02, only with `--under-arm` on aim frames (`_arms.json` "aim" >= 0.5) | positive armpit test (`collisions.pocket_gap`): a section of the stock's rear 35% (from the end nearest a shoulder; the author's pose runs the stock through the pocket with the butt behind the back: the end alone read 7.4 cm) lies 0.1-0.75 of the upper arm below the shoulder joint (the author's accepted aim: 0.67-0.72), not outside the arm's axis, at most the arm's + stock's radius in front of or behind it, within 6 cm of the torso and of the upper arm skin. Kusznik r6: 15.8 cm (butt on the forearm); missing `_arms.json` = skipped |
| | prop_in_pocket | 0.045 (`collisions.POCKET_REST`), only with `--under-arm` on aim frames | the stock resting in the armpit's skin: points of the stock's rear 35% in the torso or in the butt-side upper arm's top 30% (`collisions.POCKET_ARM`, the fold at the shoulder joint), taken out of `prop_in_body` on those frames. The author's accepted aim on Kusznik (round 8): 3.9 cm on the ribs, which the general 1.5 cm failed. Further down the arm it is the elbow: with the whole upper arm exempt, the solver's s8 (stock 3.3 cm in the arm's middle, elbow pressed to the body; author: "it goes into the elbow, not the armpit") passed; now it fails `prop_in_body` / `prop_in_upper_arms` `upper_arms.R` 3.3 cm |
| | hands_in_torso | 0.02 | |
| | forearms_in_torso | 0.045 | an approved archer pose had 4.8 cm of forearm in the belly |
| | fingers_in_head | — (reported only) | finger and claw skin in the head: `hands_in_head` is the palm only (fingers are left out of it). Padlinozerca's claws entered the head only together with the palm (round 1 s1-s3: claws 5.2-11.7 cm, palm 6.0-11.8 cm), and the approved Kusznik aim has 1.4 cm of fingers at the cheek, so there is no limit yet |
| | fingers_in_prop | 0.008 | fingers on the stock, not in it. On the own skeleton the thumb's metacarpal (`thumb.1`, from the wrist) is a finger, so its thick base counts here; on a Mixamo rig that skin is "hand" and not measured at all (approved crossbow shot: hand skin up to 5.9–8.2 cm inside the stock; Kusznik on `amts`: thumb base 2.3 cm, hand 5.8–7.0 cm) |
| joints | wrist_bend_L/R | 85 | the hand against the forearm, one cone in any direction. Reported only for a hand that holds a weapon: the two rows below gate that hand |
| | wrist_twist_L/R | 60 | hand twist vs the forearm |
| | wrist_flexion_L/R | 50 | a hand that holds a weapon (a recipe's; both hands when the prop solver's prop is in them): the wrist's bend since the rig's rest pose, split by direction (`pipeline/lib/wrist.py`; the two parts in quadrature are the bend). This part goes toward the palm or the back of the hand. Limit = the largest on the author's own hand-posed sword frames + a margin: the knight's strike frame as he re-posed it 24° (extension), his four earlier keys 20-43° (the wind-up key 43°). Skipped with fewer than two fingers below the hand (its sides cannot be told apart) |
| | wrist_deviation_L/R | 25 | the same bend's sideways part, toward the thumb or the little finger. The author's rule for any held weapon: "the wrist should practically always be in one line with the forearm, at most a small deviation". He circled the knight's strike (frame 19): the forearm level, the fist hanging under it, 74° toward the little finger; the cone passed it (74 < 85). The same frame as he re-posed it 16° (forearm lowered, elbow 119° -> 137°); his four earlier keys 5-20°. The clip accepted before the rule fails on frames 16-28 (27-88°), the knight's idle on 30-97 (25-42°), Kusznik's crossbow shot at 59° right / 36° left (flexion 54° right). Fix the forearm (elbow angle, the weapon's path), never the fist or the hold |
| | upper_arm_twist_L/R | 100 | the upper arm turned about its own axis since rest, against its parent bone (measured as the wrist twist). The arm "wrung" under a weapon: knight round 9, the author on the right arm: "the sword has a fairly good path, but the arm twists and contorts" at 132° (frames 21-27: 74-132); accepted after `swing_arm` solved the arm again under the same path at 56°. The accepted clip's left arm turns 80°; Kusznik, Wybuchacz and the knight's idle 16-55° |
| | elbow_above_shoulder_L/R | 0.10 | the elbow joint above the shoulder joint while the wrist is below the top of the head bone (an arm raised overhead is not counted). Same two verdicts: rejected +11 to +19 cm at the wind-up and on the return (frames 10-11, 15, 26-29), accepted +6.3 cm (one frame); other clips 0 |
| | forearm_roll_L/R | — (reported only) | the forearm turned about its own axis against the upper arm. No limit: the accepted knight clip rolls it 85-105° through the wind-up and Kusznik holding the crossbow 99-145°; the rejected arm reached 180° |
| | head_yaw, head_pitch | — (reported; warning) | the head's forward axis against the way the rest pose faces (across the shoulder joints). `audit.json` `head` holds the clip's mean and max; above a mean yaw of 20° (`HEAD_YAW_WARN`) the audit prints `WARN head` and the review page marks it. Knight round 9: Kimodo's attack looked up to 43° to the side, 26° on average, and nothing said so; accepted with the head locked forward (yaw 0-1°, pitch 3°). Wybuchacz mean 6°, Kusznik 9°. Not scored: a glance is a choice |
| | key_hand_rot_L/R | 50 | hand rotation off the approved key pose on its key frame (armature space, only with `--key-hands` from `key_hands.py`; skipped otherwise; reported only with a prop in the hands and for a hand a recipe solved again, `sets_hand` in its report: `swing_arm` leaves the accepted knight cut at 58). Knight round 3, 8 samples straight from Kimodo: worst key 101-176 deg with the hand 2-8 cm from its target; after `key_hands.py` (wrist from the poses) 0-5 deg, round 7's right hand up to 9 |
| | stretch | 0.30 | body mesh edge growth vs rest = a wrong bone weight (a "stick" from a claw weighted to the foot). Walk: broken rig 94 cm, fixed 4; a rag between the legs 18 cm (walk), approved shot 12 cm. A length ratio did not separate them (short edges after decimation) |
| | skin_tear | 0.08 | share of the shoulder skin (faces on the clavicle and the upper 45% of the upper arm) whose area grew over 2x rest: torn, faceted shoulder (author: "the left shoulder disappeared", 11-16%). Rig before the limb core 0-1%, approved Mixamo shot 5.3%. `stretch` (edge growth in cm) did not see it: no edge grew 30 cm. Own skeletons and Mixamo |
| | face_skew | 0.025 | the face dragged to one side: skin bound partly to the head (head weight 0.3-0.9; on the own rig the rest is on the top spine bone, the neck carries no skin) off the head moved rigidly, mean offset across the shoulders in the head's rest frame. A head turned about its own axis against the chest shears that skin; edge stretch and `skin_tear` do not see a shear (the edges keep their length: Kusznik's face edges p95 1.35x skewed, 1.38x in the author's fixed pose). Kusznik round 8: head turned 20 deg against the chest, 4.0 cm (author: "the face is skewed again"); the author's own pose (head 7 deg) 0.8 cm; `prop_in_hands` turns the head back to 5 deg: 1.1 cm. The hold (f0, head 15 deg) at 3.2 cm passed a 3.5 cm limit but looked skewed beside the aim; the limit is 2.5 cm (m1 Mixamo 2.2 cm) |
| | skin_twist / skin_spread | 120° / 0.5 | arm "candy wrapper" (section "Skin" below): broken swing 210–260° / 0.45–0.80, approved up to 60° / 0.41 |
| smoothness | elbow_jump | 0.03 | raw Kimodo 1.6 cm; 0.08 let 15 cm per frame through |
| | hand_jump | 8° | raw 4.8–5.1° |
| | pelvis_shake | 4° | pelvis yaw (hip line) minus its centred 5-frame mean (`shake.py`): a pelvis snapping to each key pose and back. Knight round 7 (root forced forward between turned key poses; author: "the knees shake") 6.4–8.7°; rounds 3 and 5, idle, Kusznik, m1 up to 1.6° |
| | knee_shake | — (reported only) | the same on the knee position: round 7 3.4–4.1 cm, the others up to 2.1 cm (m1 Wybuchacz); too close for a limit yet |
| | finger_jump | 6° | raw 0° |
| | prop_jump | 0.10 | prop teleport |
| | head_jump | 4° | raw 1.0°, walk 0.5°, every shot version 1.3° |
| | loop_seam_deg | 15° | last frame vs first (head, hands): walk 1.8°, an older shot 4.5°; a 26° head pop was reported by eye; 7 intermediate versions had 30° and the audit was silent |
| | loop_seam_m | 0.12 | elbows on the seam; = 4 × elbow_jump (one frame); walk 1.4 cm, older shot 6.1 cm |
| | prop_rot_jump | — | info: raw 0.4°, versions 1.7–2.5°; no bad sample |
| grip | hand_to_prop_L/R | 0.03 | gap between palm skin and the prop: with the grip solver 0–0.1 cm, without (raw) 50–62 cm |
| | prop_above_head | — | info: prop centre above the top of the head. 0 in all 20 versions on disk, so no limit; the offset from the requested pose is in the `PROP POSE` line |
| | finger_tip_gap | 0.03 | farthest tip of the own skeleton's fingers (thumbs out) from the prop: a finger standing straight (Kusznik's right middle finger, 8.2 cm). `loose_fingers` measures a finger's nearest point, and its base touched the stock. Skipped without `finger_chains` in the skeleton profile (Mixamo's finger tips gave constant, unreliable values) |
| | finger_tip_fold | 0.05 | share of a fingertip's skin (faces of each chain's last bone, thumbs too) turned over 120° against its own bone: a tip folded back over itself (author: "the green finger's tip is bent oddly", 23%; 0% after the weight fix). Joint angles did not show it (91° / 55°, natural): stray hand weight on the claw pulled it back. Skipped without `finger_chains` |
| | finger_curl_L/R | 220 | the most any finger of a hand that holds a recipe weapon bends, summed over its bones (each bone's turn since rest): a finger looped onto itself round the grip. Knight: a fist computed on a thick placeholder grip and used on a thin one 270-297° per finger, the index tip 1.6 cm from its own base (author: "one finger is curled up"); his own hand-posed fist on the same sword 58-109°; a fist computed to wrap that grip 154-160° (rejected by eye, not a loop). Skipped for a hand without a recipe weapon. `one_hand_weapon` reports the rest of the fist (skin inside the grip, a phalanx off it), not scored |
| | loose_fingers | — | info: fraction of fingers farther than 2 cm from the prop. 20–40% in every version: does not separate good from bad |

| feet | feet_above_ground | 0.15 | lowest foot skin point (foot, toe, toe_end bones) above the clip's OWN ground (its lowest foot point over the whole clip; `combine_actions.py --ground` moves every action onto one ground later, so only a change of height inside the clip is a defect). Accepted: m1 Wybuchacz 6.8 cm, Kusznik 2.6 cm, library walks 7.0 / 9.3 cm, knight's text samples ≤ 2.2 cm. Padlinozerca round 3 (key poses at standing hip height, F17): s0 41 cm, s1-s3 41-60 cm; s0 grounded by script 2.8 cm. An intended jump fails it too: raise it with `--limits` for that action |
| | foot_slide | 0.08 | net ground-plane travel of a planted foot (its skin within `feet.CONTACT` = 3 cm of the ground in two samples in a row; the median of that skin, the lowest vertex jumps heel/toe) over `SLIDE_FRAMES` = 2 frames, minus the clip's "treadmill" (median travel of all contact steps: a walk in place moves its planted foot back at walking speed, raw 13-15 cm; standing actions ~0). Accepted: walks 5.2 cm (at the loop seam), attacks and idles ≤ 3.2 cm. Padlinozerca s0 grounded: right foot 63 cm on landing (fr. 28-30), left 24 cm at take-off (fr. 21). A 4 cm contact let a walk's toe roll read as 46 cm |
| | foot_hanging | — (reported only) | one foot on the ground, the other this high (its lowest point): Padlinozerca's grounded crouch stands on the right foot with the left 30 cm up for 0.8 s (Kimodo's leg bend). A walk's swing foot reaches 16 cm; no accepted step or kick in the data to tell them apart, so no verdict |

Feet metrics need the whole clip (ground, treadmill): `--frames` measures none.
Grip metrics are measured only when the prop should be in the hands (`--prop` without `--rest-is-normal`).
`--no-loop` skips the loop seam (in `character.json`: `"loop": false` on the action).
`--limits file.json` overrides single limits (only from a measurement, with an entry here).
`--rest-is-normal` adds to the limit the penetration the model already has at rest – only for a prop carried where it was
modelled (e.g. a crossbow on the back in the walk).
`--frames 10,45,56`: only these frames, no smoothness – for a quick grip try (`variants.py --frames`).
`--under-arm`: also scores `prop_in_upper_arms`, `rest_gap` and `prop_in_pocket` (a stock under the armpit; both pocket checks need the
`<glb>_arms.json` that `prop_in_hands` writes, with the aim weight of every frame).

**±0.1 score noise:** the audit samples 700 prop vertices and every other hand vertex; after a re-export of the GLB the vertex
order is different. The same approved shot in another file: 1.40 and 1.28 while `compare_motion` = IDENTICAL.
Whether a motion changed is answered by `compare_motion.py`, not by a score difference.

## What the audit still does not see (use close-ups)
- hands held at the head without touching it. Padlinozerca s0 (claws over the face in both key poses, audit 1.18) has
  nothing in the head: claws 3-9 cm off the head skin all clip (round 1), 4-16 cm (round 2). A distance limit would fail
  approved motions: Wybuchacz's crouch has the hands a median 3.4 cm from the head (within 10 cm for 56% of the clip),
  Kusznik's aim within 10 cm for 41%. Face covered as seen from the front (rays from the face skin) was 0 in that s0: the
  claws are above and around the hanging head, not in front of it. The hand-movement measure (README "Choosing a sample")
  drops round 1's s0, not round 2's;
- which side of the hand touches the prop (palm or back): the sign comes from the rig, so a measure with the same sign would
  agree; the rig preview (thumb in red) and the hand close-up from below guard it;
- "prop not where it should be" below the head: the `LIMIT prop` line from `prop_in_hands` (offset at its limit),
  `PROP POSE` (largest offset and frame) and the `offset` field in `*_arms.json`;
- naturalness: elbow up, fingers wrapped the wrong way.

## Rig symmetry (auto_rig, before Blender)
A side detected on a prop or a wrong layer passes every motion audit: Kusznik's left elbow sat 8 cm behind the arm (the
crossbow on the back) and seven grip rounds were tuned on that arm. `auto_rig.symmetry_gate` mirrors the right joints in the
median midline of the pairs (Kusznik's model stands 0.8 cm off x = 0) and stops the rig past a limit; `--allow-asymmetry`
(`character.json` `rig_asymmetric`) for a model posed asymmetrically. Fingertips and outer finger joints are not compared.
Worst mirrored pair, % of the character height (2026-11-20, detection of `8f3ab95` + body-only prop):
- **body: limit 3%** (5.7 cm at 1.9 m). Good: Kusznik after the elbow fix 1.6 (forearm 3.0 cm), Boss Warlord 2.6
  (3.7 cm), Strażnik Brodu 1.6, 15 other rigs 0.2-1.2. Bad: Kusznik before 4.8 (elbow 9.1 cm), Dzwonnik 5.3, Rycerz 8.2,
  Bosak 10.7, Flisak with the pole joined 12.5 (its body alone 1.2), Planetnik 19.3. Also over the limit: Utopiony Zbrojny
  3.3 (one arm), Poborca 4.3, Głębinnik Brzeg 4.4;
- **knuckles: limit 5%** (9.5 cm). Generated hands differ between sides for real: our approved Wybuchacz 6.1 cm (3.2%),
  Flisak 6.2 (4.0). Kusznik's knuckles went 5.3 ->
  0.6 cm with the elbow fix: the elbow catches that, the knuckle limit catches a hand found on a prop (Flisak joined 17 cm).
Symmetric errors (both arms shifted the same way) are not caught; nothing checks the detected joints against a
reference (the numbers above come from detections before the 2026-11 change of proportions, see `auto_rig.py` sources).

## Arm skin and alpha
Bone twist and mesh collapse did NOT separate good from bad (an approved overhead strike has a 136° elbow/wrist twist, more
cross-section collapse, shear and LBS-vs-DQS difference than a rejected swing; the crossbowman has a 145° elbow twist): the
arm over the head is twisted, but dark and smooth. What separated them is what the eye reads as a "candy wrapper": skin
stripes along the arm turning into a spiral (`pipeline/lib/skin.py`).
- the angle of every vertex around the segment axis (upper arm with shoulder, forearm) relative to the torso carried by the
  shortest rotation; circular regression angle = a + twist·t: **`skin_twist`** (deg per segment length) and
  **`skin_spread`** = 1 − coherence;
- **limits 120° / 0.5**. The rejected overhead swing: twist 210–260°, spread 0.45–0.80, FAIL on both arms.
  Approved: overhead strike (108 fr.) 60° / 0.41, crossbow shot 40° / 0.22, walk and idle ≤30° / 0.07, an entry with a
  hand-set pose 40° / 0.19;
- keep a known-bad pose script as a regression pattern: `skin_check.py --script` on it must give FAIL, and the same numbers
  after any change to `skin.py` (`tests/test_skin.py` covers the synthetic case).

**Alpha** (`pipeline/checks/alpha_check.py`): body islands = visible pieces of one blob of the raw layer cut off by a mask.
A frame where a bridge mask cut fingers above a boat ("you can see the boat through the fingers", the render had full alpha):
526 px in 2 islands; older versions 170–1349 px; approved frames 0 px (the mask edge gives specks of 2–19 px; limits 30 px
per island, 100 px per frame).

## Calibration (crossbowman)
- library walk on `rig_ai.glb` with the crossbow on the back: **OK** (rest clean);
- version 3 (rejected): FAIL – prop in head 7.8 cm, hands in head 8.1 cm, wrists 149° / twist 179°;
- raw Kimodo after retarget: FAIL – hands in head 7.9 cm, right hand twist 133°;
- an earlier accepted-by-eye version (later replaced): FAIL 7.29 = penetration 7.07 + joints 0.17 + smoothness 0.05;
- **approved shot (key poses): FAIL 1.40**, penetration only (hand in head 0.65 cm, forearm 1.1 cm, hand in torso 2.3 cm,
  fingers in the crossbow 1.6 cm). This is the regression pattern: `chain.py` on its BVH with its motion file and
  `compare_motion.py` against the approved GLB must give IDENTICAL.
A change to a measure = rerun these cases: walk OK, version 3 and raw FAIL, approved shot the same numbers.
