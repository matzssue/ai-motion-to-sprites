import { describe, expect, it } from "vitest";
import { CATALOG, compareMetrics, formatLimit, formatShare, formatSide, formatValue, metricGroup, metricLabel, metricUnit } from "./metrics";

describe("metric labels and units (review_page.py)", () => {
  it("uses the review page labels and falls back to the key", () => {
    expect(metricLabel("hands_in_head")).toBe("hand in head");
    expect(metricLabel("prop_in_clavicles")).toBe("prop in shoulder");
    expect(metricLabel("new_metric")).toBe("new_metric");
  });

  it("picks units by the same prefixes as fmt()", () => {
    expect(metricUnit("wrist_bend_L")).toBe("deg");
    expect(metricUnit("wrist_twist_R")).toBe("deg");
    expect(metricUnit("loop_seam_deg")).toBe("deg");
    expect(metricUnit("loop_seam_m")).toBe("cm");
    expect(metricUnit("skin_spread")).toBe("percent");
    expect(metricUnit("loose_fingers")).toBe("percent");
    expect(metricUnit("stretch")).toBe("cm");
    expect(metricUnit("skin_tear")).toBe("percent");
    expect(metricUnit("finger_tip_fold")).toBe("percent");
    expect(metricUnit("face_skew")).toBe("cm");
  });

  it("knows every metric of the audit (catalog.json from audit_metrics.METRICS)", () => {
    expect(CATALOG.length).toBeGreaterThan(30);
    for (const m of CATALOG) {
      expect(metricLabel(m.key)).not.toBe(m.key);
      expect(metricGroup(m.key)).not.toBe("other");
    }
    expect(formatValue("skin_tear", 0.143)).toBe("14%");
    expect(metricGroup("prop_in_pocket")).toBe("penetration");
    expect(metricGroup("finger_tip_gap")).toBe("grip");
  });

  it("formats like review_page.py", () => {
    expect(formatValue("hands_in_head", 0.0065)).toBe("0.7 cm");
    expect(formatValue("hands_in_torso", 0.0708)).toBe("7.1 cm");
    expect(formatValue("wrist_twist_L", 74.2)).toBe("74.2°");
    expect(formatValue("skin_spread", 0.41)).toBe("41%");
    expect(formatValue("stretch", null)).toBe("-");
    expect(formatShare(0.07)).toBe("7%");
    expect(formatLimit({ key: "hands_in_head", limit: 0.0052, reportedOnly: false })).toBe("0.5 cm");
    expect(formatLimit({ key: "prop_rot_jump", limit: null, reportedOnly: true })).toBe("reported only");
    expect(formatLimit({ key: "hands_in_legs", limit: null, reportedOnly: false })).toBe("no limit");
    expect(formatSide("L")).toBe("left");
    expect(formatSide(null)).toBe("");
  });

  it("orders by audit group, then audit order, unknown metrics last", () => {
    const keys = ["hand_to_prop_L", "zz_new", "elbow_jump", "stretch", "hands_in_head", "wrist_bend_L"];
    expect(keys.sort(compareMetrics)).toEqual(["hands_in_head", "wrist_bend_L", "stretch", "elbow_jump", "hand_to_prop_L", "zz_new"]);
    expect(metricGroup("stretch")).toBe("joints");
    expect(metricGroup("zz_new")).toBe("other");
    expect(metricGroup("hands_in_legs")).toBe("penetration");
  });
});
