import { describe, expect, it } from "vitest";
import { REPORT, SAMPLE_ROWS } from "./fixtures";
import { markerAt } from "./marker";
import { parseReport, parseSamples } from "./parse";

const report = parseReport("audit.json", REPORT);
const samples = parseSamples("audit_samples.json", SAMPLE_ROWS);
const times = samples.map((s) => s.t);

describe("markerAt", () => {
  it("follows the sample nearest to the playhead", () => {
    expect(markerAt(report, samples, times, "hands_in_head", 70.4)).toEqual({
      where: [0, 0, 0.5],
      value: 0.0065,
      side: "R",
      frame: 70.5,
    });
  });

  it("hides where the nearest sample has no point for the metric", () => {
    expect(markerAt(report, samples, times, "hands_in_head", 71)).toBeNull();
  });

  it("uses the error's worst point when there are no samples", () => {
    expect(markerAt(report, null, [], "hands_in_head", 0)).toEqual({
      where: [-0.055, -0.241, 0.5615],
      value: 0.0065,
      side: "R",
      frame: 71,
    });
    expect(markerAt(report, null, [], "wrist_bend_L", 0)).toBeNull();
  });
});
