# One-handed weapon attack

Use when: a fast attack with a weapon rigid in one hand (a sword cut, an axe or mace blow) whose shape you fix with many
  key poses close together: wind-up, strike, follow-through and the return to guard inside about a second.
Not for: continuous or slow motion (walk, idle, a stance change): text and a few key poses through the model, the general
  path in the skill. Two-handed grips, thrusts and throws: not made yet.
Route: legs and hips from the model through the key poses; spine, arms and hands from the key poses themselves; head
  locked forward; the weapon arm solved again under the weapon's path; then the weapon and the fist.

Made once and accepted: the knight (own skeleton `amts`, 1.90 m), a diagonal sword cut from over the right shoulder to
the left hip and back to guard, 56 frames at 24 fps, looping. Frames and centimetres below are that clip's; the route and
the order are what carries over.

## Route

| Part | Comes from | Why |
|---|---|---|
| legs, hips | the motion model (Kimodo) through the key poses | weight shift, the step and the hip turn are what it does well |
| spine above the hips, shoulders, arms, hands | the key poses, interpolated (`upper_body`) | between 9 keys in 38 frames the model folds the arm: see Rejected |
| head, neck | turned to the facing direction (`head`) | the model looked up to 43 deg to the side through the whole clip |
| weapon arm (shoulder to hand) | `swing_arm`: solved again under the weapon's path | the posed arm, interpolated joint by joint, came out wrung |
| weapon, fist | `one_hand_weapon` | rigid in the hand; it also measures the final arm against the weapon |

Decide first which kind of motion it is. Continuous motion (a walk, an idle that sways) has no pose the viewer must
read on one exact frame: write the text, give the model its two or three poses, and stop there. An attack is read on its
key frames, so its upper body is not left to the model.

## Key poses

Nine on the knight, on the moments a viewer reads: ready 0, raise 8, wind-up-in 12, wind-up 14, strike 20, follow 22,
passing 25, withdraw 30, recover 38; the clip ends in the first pose (frame 55). Dense where the weapon is fast (three keys
in the 8 frames around the strike), sparse in the settle. Pose the whole body and the weapon in every key (the pose scene:
`pose_edit_scene.py`); the placement of the weapon in the hand and the closed fist are read from that scene once
(`one_hand_weapon.py --read-scene`).

A pose between two keys that the interpolation gets wrong is a breakdown, not a tenth key for the model: the knight's
blade passed upright in front of the helmet on its way from overhead to the strike (frame 17) and again on the return
(28), 4 cm from it on frame 18 and 9 cm on 27. Two breakdowns of the sword arm, on 17 and 28, moved it to 24 and 21 cm.

## Steps

1. Motion file as for any AI action: `phases` (one sentence each), `key_poses` (name -> frame), `loop_blend_s`. Run
   `character.py` to the pose review, pose the keys, have the poses approved (`poses_approved.json`). Skill, section 3.
2. Add to the motion file (all four are in `examples/one_handed_attack.example.json`):
   - `"upper_body": {"tangents": {...}, "breakdowns": {...}}`. Tangents: speed through a key against the default; the
     knight uses 1.6 on the strike (the hand does not brake into it) and 0.25 on the follow (it brakes after contact).
     Breakdowns: per frame the wrist moved from where the track puts it and the blade turned to a world direction.
   - `"head": {"mode": "lock"}` (an idle that glances around: `"mode": "keep", "keep": 0.35`).
   - `"recipe": [{"name": "swing_arm", ...}, {"name": "one_hand_weapon", ...}]`, in this order: the second one measures
     the arm the first one made. Inputs: `pipeline/recipes/README.md`.
3. `character.py` generates the samples through the poses and runs each through `chain.py`: retarget ->
   `pose_upper_body.py` -> `head_forward.py` -> `key_hands.py` (measuring only) -> merge -> `swing_arm` ->
   `one_hand_weapon` -> audit.
4. Look (next section), then change `upper_body` or `path_edits` and run `chain.py` again on the SAME sample:
   `python pipeline/chain.py --rig <work>/rig_ai.glb --motion <motion>.json --bvh <work>/<action>/kf/kf_s<N>.bvh
   --out <work>/<action>/p --key-poses <poses>.glb --key-frames 0,8,12,... [--skeleton X]`. Everything after the
   retarget is this repo's code, so a round costs seconds and no model run. `character.py` would generate again, because
   the motion file changed; go back to it when the motion is approved (`"approved"` in character.json).
5. What the numbers should say on the way: `HEAD lock: yaw ... -> 0..1`; the recipe line of `swing_arm` (twist, roll,
   bend before -> after, weapon off its path 0.0 cm); `one_hand_weapon`'s weapon-in-body frames and its fist line; the audit's
   `upper_arm_twist`, `elbow_above_shoulder` and `head` lines. The accepted knight clip: audit FAIL 3.71 (hand and elbow
   jump at strike speed, wrist bend 100 deg around frame 26, wrist twist 72), upper arm 56 deg, elbow +6 cm, sword in the body on 1 of 56
   frames (0.2 cm, forearm). `key_hand_rot` of the weapon hand is reported, not scored (58 deg on the accepted clip: the
   solver turned that hand on purpose). The audit does not close a motion; the author's verdict does.

## What to look at

- Per frame, not per key: every defect of this motion sat between two keys that were both fine.
- Large close-ups of the weapon arm through the wind-up (knight: frames 11-16) and the return (23-30), from the front
  and the front-right (S and SE), about 600 px per frame. On an 8-direction sheet of small tiles a wrung arm passes.
- In motion before the verdict: a preview of S and SE over all frames first, the 8 cameras only when those two pass.
  A return path that looked right on stills put the blade between the legs when played (Rejected, below).
- The blade against the helmet and the legs in those two views; `one_hand_weapon` counts only what is inside the skin.
- The author's words for this defect were "the sword has a fairly good path, but the arm twists and contorts": judge the
  weapon's path and the arm separately, and change only the one that is wrong.

## Rejected - do not retry

- The model's own arms between dense keys (9 keys, 38 frames): the elbow folds in mid-swing, flex 22, 25, 47, 89, 65, 42
  deg over frames 16-21, and twists on the return (forearm turning 43-66 deg per frame on 24-27); rejected twice.
- The model's post-processing that pulls the clip onto the keys (Kimodo `motion_correction`): hits the keys exactly and
  throws the hand up to 116 cm between them.
- A monotone (braking) interpolation of the posed arms: no fold, but the blade passes upright in front of the face on 17
  and 28 (4 and 9 cm from the helmet) and the hand brakes at every key; hence Catmull-Rom tangents and two breakdowns.
- Keeping the interpolated posed arm under the weapon: upper arm turned 132 deg about its own axis, elbow 11-19 cm above
  the shoulder on the wind-up and the return; the author's verdict quoted above. `swing_arm` brought it to 56 deg, +6 cm.
- Limiting the weapon's roll in the solver to +-30 deg, then freeing it: the same arm either way. The blade's direction
  and the grip's position force the arm, not the roll; do not tune the roll range or the cost weights (over-limit
  penalties x200 and x1000, step weights 0.08-0.4: the same frames stay over the targets).
- Small tilts of the blade at the wind-up: 5 deg changes nothing; it takes 40 deg forward, which is a different pose.
- A straight arm at the wind-up (elbow flex 11-12 deg although the grip is within reach): move the grip toward the head
  instead, `path_edits` with `move_cm` 20 on the wind-up frames (flex 86 deg, elbow +2 cm). Tilting the blade 40 deg
  forward instead left the elbow 16 cm above the shoulder.
- Smoothing the weapon's path on the return (blade direction, with or without the grip, re-timed at a constant speed over
  23-28): judged fine from stills; in motion the blade drops point down between the legs on 24-25, the sword is 0.6 to 11
  cm inside the left leg and the wrist flips (twist -67 to +60 deg in one frame). Keep the posed return.

## Swapping the weapon

The attack is accepted and the weapon changes (the knight: a placeholder sword replaced by the game's, grip radius 2.1-2.9
cm against 1.3-2.2). Nothing is generated or posed again; three things are kept and one is fitted.

- **The hand-posed fist and hold stay.** Read them from the author's own key in his pose scene
  (`one_hand_weapon.py --read-scene <weapon object> --frame <his key>`): `fingers` and `in_hand`. Check first that the
  scene is his: `pose_diff.py` between his file and whatever the pipeline carries (see the rule below).
- **Fit the grip to the fist, not the fist to the grip.** The fist was posed on a grip of some thickness; bring the new
  weapon's grip to it on the model (the knight: the wrap scaled x1.4 about its axis, 1.8-3.0 cm). `one_hand_weapon`
  prints the fist against the grip (flexion per finger, skin inside, a phalanx off) and the audit scores `finger_curl`.
- **The blade keeps its path.** `swing_arm` with `path_hold`: the old placement in the hand (and the old weapon's
  `grip` and `tip`, when the weapon is another mesh). The path is read with the old hold and the arm is solved for the
  new one. The knight's hold changed by 41 deg (blade direction 17, roll about the grip 38) and 3.1 cm at the grip.
- **Ease at the frames shared with other clips.** `pin: [0]` keeps the clip's arm on the loop frame, so that frame
  joins the idle (hand 2.1 cm / 1 deg off it; solved freely it was 7.4 cm / 30 deg). With a new hold the pinned frame's
  weapon is off the path, on that frame only: without `ease_frames` the sword jumps (0 -> 1: 18.1 deg / 2.1 cm, 54 ->
  55: 17.5 deg / 3.1 cm); with `ease_frames: 5` 2.9 deg and 1.9 deg, frames 5-50 untouched. `other_arm_blend` brings the
  other arm to the idle's first frame at both ends (1.2 cm / 3 deg, was 4.5 cm / 55 deg). The idle gets the same
  `one_hand_weapon` entry; its arm is not solved again.
- **Stills before any full render**: the fist from two sides on one frame, then frames 0-3 and the last four in the two
  preview cameras. Every fist problem of this swap was visible on one still; a full 8-camera render of each try was not
  needed.

`examples/weapon_swap.example.json` is this case as one motion file. The knight's attack after the swap: sword in the
body on 0 of 56 frames, the fist covers 70-74% of the grip, `finger_curl` 109 deg (limit 220), audit FAIL 3.79 on the same
five checks as before the swap.

**Rule: hand-posed keys are read-only input.** A step that writes them again (a fix script, a re-export, a fist put on
every key) prints `pipeline/checks/pose_diff.py -- --a <his file> --b <the new file>`: per bone the largest change, most
changed first. Call a pose or a fist "approved" only when the author saw exactly that one. The knight's "approved fist"
was a computed fist a fix script had written over his fingers on every key: the diff of his file and the rewritten one
shows 36 of 65 bones over 1 deg, all 15 finger bones of the sword hand by 41-112 deg. His own fist bends 58-109 deg per
finger, the computed one 270-297.

Rejected - do not retry:
- A computed fist on a gauntlet with fused fingers, three ways: each joint closed until its phalanx touches the grip; one
  curl scale per finger with a shifted grip; joint angles from the wrap formula (curl 154-160 deg). The numbers pass
  (nothing inside, pads on the grip) and every one looks worse than the hand-posed fist.
- Thickening the grip to hide a looped finger: the computed fist's index stood 1.9 cm off the thin grip, its tip showing
  under the gauntlet plate (the author: "one finger is curled up"), and still 1.2 cm off the grip scaled x1.4. The loop
  is the fist's (flexion 270-297 deg, the index tip 1.6 cm from its own base), not the grip's.

## Not covered

- Joining clips is `pin` / `ease_frames` / `other_arm_blend` on the attack (above); the hips, feet and head at the join
  are whatever the two clips have (the knight: hips 0.1 cm, feet 1.2-2.4 cm).
- The other arm is the poses' and hangs from the model's hips: on the keys the hands sit a little off the posed spot in
  the world (`key_hands.py` reports it per key).
- One character, one cut. A second one-handed attack that goes differently belongs in this page; a different kind of
  motion gets its own.
