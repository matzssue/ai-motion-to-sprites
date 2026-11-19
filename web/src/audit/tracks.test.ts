import { describe, expect, it } from "vitest";
import { REPORT, SAMPLE_ROWS } from "./fixtures";
import { parseReport, parseSamples } from "./parse";
import { buildTracks, failRanges, nearestSampleIndex, worstSampleInRange } from "./tracks";

const report = parseReport("audit.json", REPORT);
const samples = parseSamples("audit_samples.json", SAMPLE_ROWS);

describe("timeline tracks", () => {
  it("finds runs of consecutive samples strictly over the limit", () => {
    expect(failRanges([0, 1, 2, 3, 4], [5, 1, 5, 5, 1], 1)).toEqual([
      [0, 0],
      [2, 3],
    ]);
    expect(failRanges([0, 1, 2], [2, 2, 2], 1)).toEqual([[0, 2]]);
    expect(failRanges([0, 1], [1, 1], 1)).toEqual([]);
  });

  it("builds one track per metric with data, in audit order", () => {
    const tracks = buildTracks(report, samples);
    expect(tracks.map((t) => t.key)).toEqual(["hands_in_head", "wrist_bend_L", "prop_rot_jump"]);
    const head = tracks[0]!;
    expect(head.label).toBe("hand in head");
    expect(head.failRanges).toEqual([
      [70.25, 70.5],
      [71, 71],
    ]);
    expect(head.error?.at_frame).toBe(71);
  });

  it("treats a missing value as 0 and a no_limit metric as reported only", () => {
    const rot = buildTracks(report, samples).find((t) => t.key === "prop_rot_jump")!;
    expect(rot.limit).toBeNull();
    expect(rot.reportedOnly).toBe(true);
    expect(rot.values).toEqual([0.4, 0, 0, 0, 0]);
    expect(rot.failRanges).toEqual([]);
  });

  it("falls back to the error range without samples", () => {
    const tracks = buildTracks(report, null);
    expect(tracks.find((t) => t.key === "hands_in_head")?.failRanges).toEqual([[70.5, 71.5]]);
  });

  it("finds the nearest sample", () => {
    const times = samples.map((s) => s.t);
    expect(nearestSampleIndex(times, 70.6)).toBe(2);
    expect(nearestSampleIndex(times, 70.63)).toBe(3);
    expect(nearestSampleIndex(times, -5)).toBe(0);
    expect(nearestSampleIndex(times, 99)).toBe(4);
    expect(nearestSampleIndex([], 1)).toBe(-1);
  });

  it("jumps to the audit's frame for its range and to the worst sample for other ranges", () => {
    const head = buildTracks(report, samples)[0]!;
    expect(worstSampleInRange(head, [70.25, 70.5])).toBe(70.5);
    expect(worstSampleInRange(head, [71, 71])).toBe(71);
    const noSamples = buildTracks(report, null)[0]!;
    expect(worstSampleInRange(noSamples, [70.5, 71.5])).toBe(71);
  });
});
