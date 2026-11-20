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
    "face_skew": (0.035, "m", "joints"),
    # farthest fingertip from the prop while it is in the hands: a finger standing straight up beside the stock. The nearest
    # point of a finger (loose_fingers) is its base, which touches the stock either way
    # (own chains, thumbs out: Kusznik's straight middle finger 3.6 cm, the others 0.2-2.5 cm)
    "finger_tip_gap": (0.03, "m", "grip"),
    # share of a fingertip's skin folded back over itself (faces turned > 120 deg against their own bone): claw tips past
    # the end of the finger's bone carried hand weight and the curl pulled them back (Kusznik's right middle finger 23%)
    "finger_tip_fold": (0.05, "frac", "joints"),
}
ARM = ("upper_arm", "forearm", "hand", "spine")
# skeleton roles a metric measures (skeleton.Profile.missing): absent -> the metric is skipped with the reason, not scored
NEEDS = {
    "prop_in_head": ("region:head",), "prop_in_torso": ("region:torso",), "prop_in_legs": ("region:legs",),
    "prop_in_clavicles": ("region:clavicles",), "hands_in_head": ("hand", "region:head"), "hands_in_torso": ("hand", "region:torso"),
    "forearms_in_head": ("forearm", "region:head"), "forearms_in_torso": ("forearm", "region:torso"), "fingers_in_prop": ("fingers",),
    "wrist_bend_L": ("forearm.left", "hand.left"), "wrist_bend_R": ("forearm.right", "hand.right"),
    "wrist_twist_L": ("forearm.left", "hand.left"), "wrist_twist_R": ("forearm.right", "hand.right"),
    "elbow_jump": ("forearm",), "prop_jump": (), "hand_jump": ("hand",), "finger_jump": ("fingers",), "head_jump": ("head",),
    "prop_rot_jump": (), "loop_seam_deg": ("hand", "head"), "loop_seam_m": ("forearm",),
    "hand_to_prop_L": ("hand.left",), "hand_to_prop_R": ("hand.right",), "prop_above_head": ("region:head",),
    "loose_fingers": ("fingers",), "stretch": (), "skin_twist": ARM, "skin_spread": ARM,
    "skin_tear": ("shoulder", "upper_arm", "forearm"), "prop_in_upper_arms": ("upper_arm",), "prop_in_body": (), "rest_gap": ("upper_arm", "forearm"), "prop_in_pocket": ("upper_arm", "forearm"), "face_skew": ("head",), "finger_tip_gap": ("fingers",),
    "finger_tip_fold": ("fingers",),
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
