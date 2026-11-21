"""Audit metrics of motion_audit.py: limits, units, groups, the skeleton roles each one needs, and the verdict over
samples. No Blender here (tests run the verdict on plain rows). Limits and where they come from: README, "Quality gates"."""
import skin

# (limit, unit, group); "m" = metres for a ~1.8 m character (scaled by height), "deg" = degrees, "frac" = 0..1;
# jumps per 1/4 frame. Limit None = reported only (no bad sample yet to calibrate against).
METRICS = {
    "prop_in_head": (0.005, "m", "penetration"), "prop_in_torso": (0.015, "m", "penetration"),
    "prop_in_legs": (0.015, "m", "penetration"), "prop_in_clavicles": (0.03, "m", "penetration"),
    "hands_in_head": (0.005, "m", "penetration"), "hands_in_torso": (0.02, "m", "penetration"),
    "forearms_in_head": (0.01, "m", "penetration"), "forearms_in_torso": (0.045, "m", "penetration"),
    "fingers_in_prop": (0.008, "m", "penetration"),
    # finger and claw skin in the head (hands_in_head is the palm only). Reported only: Padlinozerca's claws went into the head
    # only with the palm (r1 s1-s3: claws 5.2-11.7 cm, palm 6.0-11.8 cm), and the approved Kusznik aim has 1.4 cm of fingers
    # at the cheek; no sample yet where only the claws enter
    "fingers_in_head": (None, "m", "penetration"),
    "wrist_bend_L": (85, "deg", "joints"), "wrist_bend_R": (85, "deg", "joints"),
    "wrist_twist_L": (60, "deg", "joints"), "wrist_twist_R": (60, "deg", "joints"),
    # elbow: raw Kimodo 1.6 cm; 0.08 let through 15 cm per frame
    "elbow_jump": (0.03, "m", "smoothness"), "prop_jump": (0.10, "m", "smoothness"),
    # raw Kimodo: hand up to 4.8 deg, fingers 0 deg. Per-frame grip choice: hand 15 deg, fingers 24 deg
    "hand_jump": (8, "deg", "smoothness"), "finger_jump": (6, "deg", "smoothness"),
    "head_jump": (4, "deg", "smoothness"), "prop_rot_jump": (None, "deg", "smoothness"),
    # seam: last frame vs first. Library walk 1.8 deg / 1.4 cm; a 26 deg head pop was reported by eye
    "loop_seam_deg": (15, "deg", "smoothness"), "loop_seam_m": (0.12, "m", "smoothness"),
    # with the grip solver 0-0.1 cm, without it (raw Kimodo) 50-62 cm
    "hand_to_prop_L": (0.03, "m", "grip"), "hand_to_prop_R": (0.03, "m", "grip"),
    "prop_above_head": (None, "m", "grip"), "loose_fingers": (None, "frac", "grip"),
    # growth of body mesh edges vs rest: a wrong bone weight gives a "stick" (a claw weighted to the foot: 2 cm -> 85 cm).
    # Walk: broken rig 94 cm, fixed 4; a rag between the legs 18 cm. A length ratio did not separate them (short decimated edges)
    "stretch": (0.30, "m", "joints"),
    # arm skin "candy wrapper" twist (skin.py): broken overhead swing 210-260 deg / spread 0.45-0.80; approved up to 60 / 0.41
    "skin_twist": (skin.TWIST_MAX, "deg", "joints"), "skin_spread": (skin.SPREAD_MAX, "frac", "joints"),
    # share of the shoulder's skin area (clavicle + upper part of the upper arm) torn into long flat facets (faces over 2x their
    # rest area): Kusznik's collapsed shoulder (upper-arm weight pulled onto the shoulder mass) 11-16%, the rig before 0-1%,
    # the approved Mixamo shot 5.3%.
    # Edge stretch (growth in cm) and the arm twist did not see it
    "skin_tear": (0.08, "frac", "joints"),
    # prop inside the upper arms (the body tree leaves the arms out): a stock butt "under the armpit" sat in the shoulder.
    # Scored only with --under-arm (motion_audit.UNDER_ARM): a stock on the shoulder sits in it by design
    "prop_in_upper_arms": (None, "m", "penetration"),
    # the prop (a separate mesh) inside ANY part of the skin - head, torso, legs, upper arms, forearms, hands - by skeleton role;
    # only the grip zone of a holding hand (its hand, fingers, the forearm's quarter next to the wrist) is left out. The report
    # names the region (`_prop_in_body`, e.g. forearms.R). Not seen before (the arms were never in the body volume): Kusznik's
    # stock through the right forearm (round 6) 3.1 cm, and the approved Mixamo shot's butt 7.4 cm inside the right shoulder
    "prop_in_body": (0.015, "m", "penetration"),
    # where the prop's rear end should rest while aiming, from skeleton roles (--under-arm = the armpit pocket: between the
    # inner upper arm and the ribs below the shoulder joint, touching both), on aim frames: its distance from that pocket.
    # Kusznik round 6: butt on the forearm in front of the elbow, 0 penetration and nothing failed
    "rest_gap": (None, "m", "grip"),
    # the stock resting in that pocket's skin on aim frames (--under-arm): its rear part in the torso or the butt-side upper
    # arm, left out of prop_in_body there. The author's accepted aim pose on Kusznik: 3.9 cm (collisions.POCKET_REST)
    "prop_in_pocket": (None, "m", "penetration"),
    # face skin (partly bound to the head) dragged sideways off the head moved rigidly: the head turned about its own axis
    # against the chest. Kusznik round 8: 6.2 cm at a 20 deg turn (author: "the face is skewed again"), the author's own
    # pose 2.0 cm, the turn removed 1.2 cm
    "face_skew": (0.025, "m", "joints"),
    # farthest fingertip from the prop while it is in the hands: a finger standing straight up beside the stock. The nearest
    # point of a finger (loose_fingers) is its base, which touches the stock either way
    # (own chains, thumbs out: Kusznik's straight middle finger 3.6 cm, the others 0.2-2.5 cm)
    "finger_tip_gap": (0.03, "m", "grip"),
    # share of a fingertip's skin folded back over itself (faces turned > 120 deg against their own bone): claw tips past
    # the end of the finger's bone carried hand weight and the curl pulled them back (Kusznik's right middle finger 23%)
    "finger_tip_fold": (0.05, "frac", "joints"),
    # feet against the clip's own ground (feet.py, AUDIT.md "Feet"). Lowest foot point above it: accepted clips up to 9.3 cm
    # (library walk), Padlinozerca's key-pose crouch at standing hip height 41-60 cm
    "feet_above_ground": (0.15, "m", "feet"),
    # net travel of a planted foot over 2 frames, the walk's treadmill taken out: accepted up to 5.2 cm (walk), attacks and
    # idles 3.2 cm; Padlinozerca's grounded leap skates 63 cm on landing
    "foot_slide": (0.08, "m", "feet"),
    # one foot on the ground, the other this high: a step or a kick does it too (a walk's swing foot 16 cm, Padlinozerca's
    # hanging crouch foot 30 cm); no accepted kick or step to calibrate against, so reported only
    "foot_hanging": (None, "m", "feet"),
    # hand rotation off the approved key pose on its key frame (--key-hands from key_hands.py; only key-pose clips). Knight
    # round 3, 8 samples: straight from Kimodo the worst key per sample 101-176 deg (positions 2-8 cm close); after
    # key_hands.py 0-5 deg on rounds 3 and 7 (16 samples), round 7's right hand up to 9. Reported only with a prop in the
    # hands: its solver sets the grip
    "key_hand_rot_L": (50, "deg", "joints"), "key_hand_rot_R": (50, "deg", "joints"),
    # pelvis yaw / knee position minus their centred 5-frame mean (shake.py): a pelvis snapping to each key pose and back.
    # Knight round 7 (root forced forward between turned key poses, author: "the knees shake") 6.4-8.7 deg / 3.4-4.1 cm;
    # rounds 3 and 5, idle, Kusznik, m1: up to 1.6 deg / 2.1 cm (m1 Wybuchacz). Knee gap too narrow for a limit yet
    "pelvis_shake": (4, "deg", "smoothness"), "knee_shake": (None, "m", "smoothness"),
}
# names on the review pages (review_page.py, web/src/audit/catalog.json); every METRICS key needs one (tests/test_audit_metrics.py)
LABELS = {
    "prop_in_head": "prop in head", "prop_in_torso": "prop in torso", "prop_in_legs": "prop in legs",
    "prop_in_clavicles": "prop in shoulder", "hands_in_head": "hand in head", "hands_in_torso": "hand in torso",
    "forearms_in_head": "forearm in head", "forearms_in_torso": "forearm in torso", "fingers_in_prop": "fingers in prop",
    "fingers_in_head": "fingers in head",
    "wrist_bend_L": "left wrist bend", "wrist_bend_R": "right wrist bend", "wrist_twist_L": "left wrist twist",
    "wrist_twist_R": "right wrist twist", "elbow_jump": "elbow jump", "prop_jump": "prop jump", "hand_jump": "hand jump",
    "finger_jump": "finger jump", "head_jump": "head jump", "prop_rot_jump": "prop rotation jump",
    "loop_seam_deg": "loop seam (rotation)", "loop_seam_m": "loop seam (elbow)", "hand_to_prop_L": "left hand to prop",
    "hand_to_prop_R": "right hand to prop", "prop_above_head": "prop above head", "loose_fingers": "loose fingers",
    "stretch": "mesh stretch", "skin_twist": "arm skin twist", "skin_spread": "arm skin spread",
    "skin_tear": "torn shoulder skin", "prop_in_upper_arms": "prop in upper arm", "prop_in_body": "prop in body",
    "rest_gap": "stock off the armpit", "prop_in_pocket": "stock in armpit skin", "face_skew": "face skew",
    "finger_tip_gap": "fingertip off prop", "finger_tip_fold": "folded fingertip",
    "feet_above_ground": "feet off the ground", "foot_slide": "planted foot sliding", "foot_hanging": "one foot hanging",
    "key_hand_rot_L": "left hand off its key pose", "key_hand_rot_R": "right hand off its key pose",
    "pelvis_shake": "pelvis shake", "knee_shake": "knee shake",
}
UNIT_SHOWN = {"m": "cm", "deg": "deg", "frac": "percent"}   # METRICS unit -> how a page shows it
REF_HEIGHT = 1.8   # "m" limits are set for a character this tall


def height(rest_z):
    """Character height from the rig's REST pose (vertex z, z up), the same for every action, sample and frame. The posed
    first frame gave Padlinozerca 1.40-2.15 m against 1.90 m at rest, so its limits moved by up to 26% between samples."""
    return float(max(rest_z) - min(rest_z))


def scaled(limits, h):
    """Limits for a character `h` m tall: metre limits scaled by h / REF_HEIGHT, degrees and fractions as they are."""
    return {k: (v * (h / REF_HEIGHT) if METRICS[k][1] == "m" else v) for k, v in limits.items() if v is not None}


def catalog():
    """Every metric in METRICS order with its label, displayed unit and group: the web viewer's copy
    (web/src/audit/catalog.json, written by `python pipeline/lib/audit_metrics.py --catalog <file>`)."""
    return [{"key": k, "label": LABELS[k], "unit": UNIT_SHOWN[u], "group": g} for k, (_, u, g) in METRICS.items()]


def catalog_json():
    import json
    return json.dumps(catalog(), indent=2) + "\n"


ARM = ("upper_arm", "forearm", "hand", "spine")
# skeleton roles a metric measures (skeleton.Profile.missing): absent -> the metric is skipped with the reason, not scored
NEEDS = {
    "prop_in_head": ("region:head",), "prop_in_torso": ("region:torso",), "prop_in_legs": ("region:legs",),
    "prop_in_clavicles": ("region:clavicles",), "hands_in_head": ("hand", "region:head"), "hands_in_torso": ("hand", "region:torso"),
    "forearms_in_head": ("forearm", "region:head"), "forearms_in_torso": ("forearm", "region:torso"), "fingers_in_prop": ("fingers",),
    "fingers_in_head": ("fingers", "region:head"),
    "wrist_bend_L": ("forearm.left", "hand.left"), "wrist_bend_R": ("forearm.right", "hand.right"),
    "wrist_twist_L": ("forearm.left", "hand.left"), "wrist_twist_R": ("forearm.right", "hand.right"),
    "elbow_jump": ("forearm",), "prop_jump": (), "hand_jump": ("hand",), "finger_jump": ("fingers",), "head_jump": ("head",),
    "prop_rot_jump": (), "loop_seam_deg": ("hand", "head"), "loop_seam_m": ("forearm",),
    "hand_to_prop_L": ("hand.left",), "hand_to_prop_R": ("hand.right",), "prop_above_head": ("region:head",),
    "loose_fingers": ("fingers",), "stretch": (), "skin_twist": ARM, "skin_spread": ARM,
    "skin_tear": ("shoulder", "upper_arm", "forearm"), "prop_in_upper_arms": ("upper_arm",), "prop_in_body": (), "rest_gap": ("upper_arm", "forearm"), "prop_in_pocket": ("upper_arm", "forearm"), "face_skew": ("head",), "finger_tip_gap": ("fingers",),
    "finger_tip_fold": ("fingers",), "feet_above_ground": ("foot",), "foot_slide": ("foot",), "foot_hanging": ("foot",),
    "key_hand_rot_L": ("hand.left",), "key_hand_rot_R": ("hand.right",),
    "pelvis_shake": ("upper_leg",), "knee_shake": ("lower_leg",),
}


def judge(samples, lim, group):
    """Errors over the limits `lim` {metric: scaled limit} -> (errors, scores per group, score, score_area).
    Skipped metrics are simply not in `lim`."""
    errors = {}
    for k, li in lim.items():
        bad = [r for r in samples if r.get(k, 0) > li]
        if bad:
            worst = max(bad, key=lambda r: r[k])
            errors[k] = {"limit": round(li, 4), "max": worst[k], "at_frame": worst["t"], "samples": len(bad),
                         "share": round(len(bad) / len(samples), 2), "range": [bad[0]["t"], bad[-1]["t"]],
                         "where": worst["_where"].get(k), "side": worst["_side"].get(k),
                         # area: mean excess over all samples, so one frame does not dominate (the score takes the maximum)
                         "area": round(sum(r[k] / li - 1 for r in bad) / len(samples), 3)}
    scores = {}
    for k, v in errors.items(): scores[group[k]] = round(scores.get(group[k], 0) + v["max"] / max(v["limit"], 1e-9) - 1, 2)
    score = round(sum(v["max"] / max(v["limit"], 1e-9) - 1 for v in errors.values()), 2)   # 0 = OK; used to pick a sample
    return errors, scores, score, round(sum(v["area"] for v in errors.values()), 3)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Write the metric catalog (labels, units, groups) for the web viewer.")
    ap.add_argument("--catalog", required=True, help="output JSON, normally web/src/audit/catalog.json")
    with open(ap.parse_args().catalog, "w", encoding="utf-8", newline="\n") as f:
        f.write(catalog_json())
