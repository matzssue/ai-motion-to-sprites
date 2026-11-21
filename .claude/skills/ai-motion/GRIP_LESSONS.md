# Why the Kusznik armpit grip took 8 rounds (2026-11-20)

Own skeleton (amts), crossbow stock under the right armpit. Seven solver rounds did not give a pose the author
accepted. The author posed frame 44 by hand in Blender in minutes. Their pose is now the base:
`local/amts_grip/keyposes_armpit/author_pose_final.{blend,json}` (rig kus13). It also has the face fixed with the head and neck bones.
Measured: 0.1 cm in the upper arm and 4.2 cm in the chest side (`spine.3`, the armpit pocket). So "inside the body" in the pocket is accepted to about 4 cm when the author poses it.

## Root causes

1. **A rig bug no audit saw.** The auto-rig took the elbow depth from every vertex in the slab, including the crossbow on the back.
   - Result: the left elbow sat 8 cm behind the arm and the upper arm came out 3.7 cm short.
   - The author: "the left arm is broken from the base", "the shoulder disappears". It could not be posed by hand either.
   - Fixed in r7. Every grip round before that tuned on top of a broken arm.
2. **Audits checked guessed shapes, not "the prop is in the body".**
   - Checks were per region: fingers in prop, hands in head, butt in upper arm. The author found the crossbow through the forearm and through the shoulder.
   - The armpit check (`rest_gap`) assumed the butt END sits in the pocket. In the author's pose the stock runs through the pocket and the butt is behind the back, so the check fails a correct pose (7.4 cm).
   - The generic `prop_in_body` (whole skin, grip zone exempt) came only in r7.
3. **No regression baseline.**
   - Each round optimised its own score. r7 was worse than the author's pose and the previous round: upper arm 5.1 vs 1.5 cm, torso 3.7 vs 1.1 cm.
   - Nothing compared a round to the author's or approved pose before showing it.
   - The notes also claimed "no pose fits under the arm", but the author's pose fits.
4. **The author's pose was transferred wrongly, twice.** This led to two rounds of proposals for a pose the author never made (a "left hand 79 cm off").
   - A JSON captured early was stale: the author kept editing.
   - The crossbow is skinned to the `kusza` bone. Its object offset works in the mesh's REST space before the armature deform, so (-0.129, -0.01, -0.021) means 13 cm back ALONG THE STOCK. It was read as 13 cm to the right.
5. **The author could not edit easily.**
   - The scene had three characters.
   - The importer's Icosphere bone shapes showed as "balls".
   - Moving the skinned crossbow in Object mode went in rotated directions, because the offset is turned by the posed bone.
   - `frame_set` after an import wiped their unkeyed pose.
6. **A prop change was proposed without measuring.** Shortening the stock by 8/15/25 cm made it worse (2.5-3.4 cm in the arm): the thick butt plate or the cut end lands in the armpit.
7. **Sessions crossed.** The grip session kept working from stale inputs after the author took over. One version of the truth (a file + its time) and a hard stop while the author edits.

## Tool changes this asks for

- **Author correction as input** (fallback, not the default; see Process): when the author fixes a pose the AI set, the tool fits the rest to it and runs Kimodo through it.
  - Read every bone's matrix_basis and the prop's EVALUATED world placement.
  - Re-apply both and compare vertices (must be 0 cm) before use.
  - Never read the object location of a skinned prop.
- **Edit scene for the author** (one command):
  - one character;
  - bone custom shapes cleared;
  - the prop as an unparented copy with its origin at its centre, so G/R work in world axes;
  - a backup `.blend` before any change.
  - Never import into or `frame_set` the author's open scene.
- **Rig symmetry gate** in `auto_rig`: mirrored L/R joints and knuckles.
  - Kusznik was 5.5 cm off before the fix and 0.9 cm after.
  - Fail above a measured limit. A broken side must stop the rig, not reach the grip.
- **Joint detection on body only**: separate props and accessories are excluded from slabs and layers.
- **Regression gate per round**: compare `prop_in_body`, `fingers_in_prop` and forearms in torso against the baseline (author's or approved pose). Worse = do not show it, say why.
- **Generic pocket check**: any section of the prop's rear part inside the armpit pocket passes, not only the end (`collisions.pocket_gap`, in progress).
- **Measure a prop change before proposing it** (length, thickness at the contact).

## Process

- **The AI sets the pose itself; the author steps in only when it fails** (author, 2026-11-20). A failed AI pose goes to the
  author at once as an edit scene, with no extra solver rounds on top of it. The author's corrected pose then becomes the
  baseline for the regression gate. Each correction is also a bug report against the solver or the audit: write down what
  the author changed (bones, prop placement, measured before/after) and fix the tool so the next character does not need it.
- Show one pose at a time, theirs or a variant next to it. Never three unlabelled copies.

## Author's f44 as a bug report (round 8)

The solver was run alone on the same body with the grips taken from the author's pose, and the author's crossbow
placement was scored with the solver's own cost. What it found:

1. **The solver scored the author's pose worse than its own.** The stock resting in the pocket counted as "in the arm"
   (4.7 cm) in the arm solver and as body hits in `prop_hits`, although the audit allowed it (`prop_in_pocket`).
2. **`grip()` bug.** A palm normal tilted along the stock moved the grip along it by the grip's whole position on the
   axis: the left palm 20 cm off the stock in both frames (also the hold).
3. **The search could not reach it.** The pinned starts turned the stock about its rear end, so a turn swung its middle
   into the chest; the descent moves 3 cm round a start. The starts now turn about the pocket point, also in front of
   the shoulder joint and slid back. The author's placement then cost 0, the solver found a comparable one (stock yaw -20
   vs -18 deg, grips within 2 cm).
4. **The audit passed the stock in the elbow** (s8, author: "the elbow is too close to the body, the crossbow goes into
   the elbow instead of the armpit; just swing the elbow out"). The pocket exemption covered the whole butt-side upper
   arm, and `prop_in_upper_arms` is read after it: 3.3 cm in the arm's middle passed. Only the arm's top 30%
   (`collisions.POCKET_ARM`, the fold at the shoulder joint) and the torso side count as the pocket now; s8 fails with
   3.3 cm `upper_arms.R`, the author's pose still passes (3.9 cm on the ribs, 0 in the arm).
5. **The elbow follows the motion's target ("down") even with the stock under it.** Swung out after the crossbow was
   placed, the arm's fold pressed the stock deeper (1.6 cm over the limit): the elbow has to be chosen with the prop's
   place. The pinned search now costs a butt-side elbow less than 0.6 of the upper arm out of the shoulder joint: the
   solver's elbow 21 cm out, the author's 20 cm.

6. **The face was skewed again** (author on s8). The key pose's head was turned 20 deg about its own axis against the
   chest (the author's fixed pose: 7). The own rig binds the jaw and mouth partly to the top spine bone (the neck has no
   skin), so the turn dragged them 6 cm sideways off the head. Not a weight bug the r7 fix could reach (the arms' weight
   is gone), and no audit saw it: edge stretch and `skin_tear` measure growth, a twist shears the skin and keeps the edge
   lengths. New `face_skew` (the face skin's sideways drift off the rigid head): s8/s12 4.0 cm, the author 0.8 cm. The
   solver turns the head back while the skew is over half the limit, after the placement: 7 deg, 1.5 cm. The hold
   (f0, head 15 deg) kept 3.2 cm under the first 3.5 cm limit and looked skewed beside the aim, so the limit is 2.5 cm:
   f0 1.0 cm, f44 1.1 cm (head 5 deg), m1 Mixamo 2.2 cm untouched. Moving the
   turn into the neck did not help (3.4 cm): only the head's turn against the chest counts.

Lesson: an exemption in the audit needs the same bounds as the thing it exempts (here: the armpit, not the arm), and
a cost the solver uses must exempt exactly what the audit exempts, no more, no less.

## Round 9: the clip did not show the approved poses (2026-11-21)

The approved aim (frame 44) was clean (audit 0.33); the clip through it failed with 20.80, the stock at the hip on frame
44 and pinned under the arm only on the recoil. Each step measured on the same merged file (Kusznik `kf_s0`, audit with
feet, failing checks in brackets):

| step | score |
|---|---|
| before | 20.80 (13) |
| aim frames from the motion file instead of the right hand's height | 25.33 (13) |
| + the approved pose's prop carried onto every frame as the target | 14.92 (9) |
| + frames solved outwards from the key frames, smoothing inside one armpit rest only | 13.65 (9) |
| + kept when it costs like on its own key frame, roll limited, held as the neighbour, loop closed | 10.74 (9) |
| + the approved arms on the key frames | 10.19 (9) |
| + face guard before the placement | 12.01 (8) |
| + face guard without its 40 deg stop | 9.02 (8) |

The guard before the placement costs score and is kept: it took `hands_in_torso` from 9.5 cm (worse than before, 6.3)
to 4.0 cm and removed `forearms_in_head`. Without the stop `face_skew` passes (5.4 -> 2.5 cm); the guard takes back up
to 62 deg of Kimodo's head turn on frames 50-71 and says so. Solver 12 min 42 s -> 5 min 50 s (frames kept or held as
the neighbour are not searched).

- **A target has to be compared with itself.** The approved place costs 140 on its own key frame (right arm 3 points
  close to the ribs). A fixed "clean enough" limit kept it nowhere; "at most 12 more than on its key frame" keeps it
  on 21 frames and the key frames end exactly on the approved pose.
- **Clean answers do not average to a clean one.** 108 pocket starts gave each frame its own pocket; the +-3 frame
  average of them was 2-9.5 cm in the body. Other pockets are now tried only when nothing near the target is clean, and
  they pay their distance.
- **Whatever moves the skin runs before the search.** The face guard turned the head after the hands were placed. The
  solver's own check and the audit disagreed by 8.5 cm on the same frame; a dump of every bone from the solved scene
  and from the exported file found one difference, the head.
- Not taken (measured): no smoothing 57.41; one pass 15.57; the stock turned with the chest 12.24; the aim's fall over
  the whole next phase 11.20, over its second half 12.51; the motion file's aim frames on a shoulder aim (m1 Kusznik
  5.16 -> 7.89).
- Left: the stock 4-5.3 cm in the right upper arm on frames 56-80, hands 2-4 cm in the torso in the hold (the approved
  hold has 2.2 cm), fingertips 5 cm off the stock on frames 76-100, an elbow jump of 4.3 cm at frame 80.
