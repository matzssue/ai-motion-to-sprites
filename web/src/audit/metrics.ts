// Names, groups and units of the audit metrics. Labels and formatting copy pipeline/review/review_page.py
// (LABELS, fmt); groups and order copy METRICS in pipeline/checks/motion_audit.py.
import type { MetricGroup, MetricUnit } from "./schema";

export const GROUPS: MetricGroup[] = ["penetration", "joints", "smoothness", "grip", "other"];

const METRIC_GROUPS: [string, MetricGroup][] = [
  ["prop_in_head", "penetration"],
  ["prop_in_torso", "penetration"],
  ["prop_in_legs", "penetration"],
  ["prop_in_clavicles", "penetration"],
  ["hands_in_head", "penetration"],
  ["hands_in_torso", "penetration"],
  ["forearms_in_head", "penetration"],
  ["forearms_in_torso", "penetration"],
  ["fingers_in_prop", "penetration"],
  ["wrist_bend_L", "joints"],
  ["wrist_bend_R", "joints"],
  ["wrist_twist_L", "joints"],
  ["wrist_twist_R", "joints"],
  ["elbow_jump", "smoothness"],
  ["prop_jump", "smoothness"],
  ["hand_jump", "smoothness"],
  ["finger_jump", "smoothness"],
  ["head_jump", "smoothness"],
  ["prop_rot_jump", "smoothness"],
  ["loop_seam_deg", "smoothness"],
  ["loop_seam_m", "smoothness"],
  ["hand_to_prop_L", "grip"],
  ["hand_to_prop_R", "grip"],
  ["prop_above_head", "grip"],
  ["loose_fingers", "grip"],
  ["stretch", "joints"],
  ["skin_twist", "joints"],
  ["skin_spread", "joints"],
];

const GROUP_OF = new Map(METRIC_GROUPS);
const ORDER = new Map(METRIC_GROUPS.map(([key], i) => [key, i]));

const LABELS: Record<string, string> = {
  prop_in_head: "prop in head",
  prop_in_torso: "prop in torso",
  prop_in_legs: "prop in legs",
  prop_in_clavicles: "prop in shoulder",
  hands_in_head: "hand in head",
  hands_in_torso: "hand in torso",
  forearms_in_head: "forearm in head",
  forearms_in_torso: "forearm in torso",
  fingers_in_prop: "fingers in prop",
  wrist_bend_L: "left wrist bend",
  wrist_bend_R: "right wrist bend",
  wrist_twist_L: "left wrist twist",
  wrist_twist_R: "right wrist twist",
  elbow_jump: "elbow jump",
  prop_jump: "prop jump",
  hand_jump: "hand jump",
  finger_jump: "finger jump",
  head_jump: "head jump",
  prop_rot_jump: "prop rotation jump",
  loop_seam_deg: "loop seam (rotation)",
  loop_seam_m: "loop seam (elbow)",
  prop_above_head: "prop above head",
  hand_to_prop_L: "left hand to prop",
  hand_to_prop_R: "right hand to prop",
  loose_fingers: "loose fingers",
  stretch: "mesh stretch",
  skin_twist: "arm skin twist",
  skin_spread: "arm skin spread",
};

const DEGREE_PREFIXES = ["wrist", "hand_jump", "finger_jump", "head_jump", "prop_rot_jump", "loop_seam_deg", "skin_twist"];
const FRACTION_PREFIXES = ["loose_fingers", "skin_spread"];

export function metricLabel(key: string): string {
  return LABELS[key] ?? key;
}

/** Region keys the audit measures but has no limit for (`hands_in_legs`) are still penetration. */
export function metricGroup(key: string): MetricGroup {
  return GROUP_OF.get(key) ?? (key.includes("_in_") ? "penetration" : "other");
}

/** Same prefix rules as `fmt` in review_page.py; anything else is a distance in metres shown in cm. */
export function metricUnit(key: string): MetricUnit {
  if (FRACTION_PREFIXES.some((p) => key.startsWith(p))) return "percent";
  if (DEGREE_PREFIXES.some((p) => key.startsWith(p))) return "deg";
  return "cm";
}

export function formatValue(key: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const unit = metricUnit(key);
  if (unit === "percent") return `${(100 * value).toFixed(0)}%`;
  if (unit === "deg") return `${value.toFixed(1)}°`;
  return `${(100 * value).toFixed(1)} cm`;
}

/** The limit column: a value, "reported only" for `no_limit` metrics, "no limit" for region keys the audit does not judge. */
export function formatLimit(track: { key: string; limit: number | null; reportedOnly: boolean }): string {
  if (track.reportedOnly) return "reported only";
  return track.limit === null ? "no limit" : formatValue(track.key, track.limit);
}

export function formatShare(share: number): string {
  return `${Math.round(100 * share)}%`;
}

export function formatSide(side: string | null | undefined): string {
  if (side === "L") return "left";
  if (side === "R") return "right";
  return "";
}

/** Audit order inside each group; unknown metrics go last, alphabetically. */
export function compareMetrics(a: string, b: string): number {
  const ga = GROUPS.indexOf(metricGroup(a));
  const gb = GROUPS.indexOf(metricGroup(b));
  if (ga !== gb) return ga - gb;
  const oa = ORDER.get(a) ?? Number.MAX_SAFE_INTEGER;
  const ob = ORDER.get(b) ?? Number.MAX_SAFE_INTEGER;
  return oa !== ob ? oa - ob : a.localeCompare(b);
}
