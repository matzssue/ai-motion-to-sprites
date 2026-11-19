// A small report in the motion_audit.py format, shaped after a real failing crossbow shot (numbers rounded).
export const REPORT = {
  result: "FAIL",
  score: 1.4,
  scores: { penetration: 1.4 },
  score_area: 0.116,
  height_m: 1.863,
  errors: {
    hands_in_head: {
      limit: 0.0052,
      max: 0.0065,
      at_frame: 71.0,
      samples: 5,
      share: 0.01,
      range: [70.5, 71.5],
      where: [-0.055, -0.241, 0.5615],
      side: "R",
      area: 0.002,
    },
  },
  maxima: { hands_in_head: 0.0065, wrist_bend_L: 61.9, prop_rot_jump: 0.4, prop_jump: 0 },
  rest: {},
  limits: { hands_in_head: 0.0052, wrist_bend_L: 85, prop_jump: 0.1 },
  no_limit: ["prop_rot_jump"],
  frames: null,
};

/** The same report from a skeleton without fingers: the finger metrics are skipped, not zero. */
export const REPORT_SKIPPED = {
  ...REPORT,
  skeleton: "mixamo_nofingers",
  skipped: { fingers_in_prop: "skeleton 'mixamo_nofingers' has no fingers", finger_jump: "skeleton 'mixamo_nofingers' has no fingers" },
};

export const SAMPLE_ROWS = [
  { t: 70, hands_in_head: 0.001, wrist_bend_L: 40, prop_rot_jump: 0.4 },
  { t: 70.25, hands_in_head: 0.006, wrist_bend_L: 41 },
  { t: 70.5, hands_in_head: 0.0065, wrist_bend_L: 61.9, _where: { hands_in_head: [0, 0, 0.5] }, _side: { hands_in_head: "R" } },
  { t: 70.75, hands_in_head: 0.003, wrist_bend_L: 50 },
  { t: 71, hands_in_head: 0.0055, wrist_bend_L: 50 },
];
