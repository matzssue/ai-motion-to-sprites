import { describe, expect, it } from "vitest";
import { clipMatchingAudit, frameToSeconds, secondsToFrame, snapToQuarter, stepFrame, wrapFrame } from "./time";

describe("frames and seconds", () => {
  it("converts at 24 fps", () => {
    expect(frameToSeconds(71)).toBeCloseTo(2.958333);
    expect(secondsToFrame(4.125)).toBe(99);
  });

  it("snaps and steps on the quarter-frame grid inside the clip", () => {
    expect(snapToQuarter(71.13)).toBe(71.25);
    expect(stepFrame(71.13, 1, 99)).toBe(72.25);
    expect(stepFrame(71, -0.25, 99)).toBe(70.75);
    expect(stepFrame(0, -1, 99)).toBe(0);
    expect(stepFrame(98.5, 1, 99)).toBe(99);
  });

  it("wraps playback", () => {
    expect(wrapFrame(100, 99)).toBe(1);
    expect(wrapFrame(-1, 99)).toBe(98);
    expect(wrapFrame(5, 0)).toBe(0);
  });

  it("finds the clip the audit was run on from its last sample", () => {
    const clips = [
      { name: "walk", duration: 1.4583 },
      { name: "attack", duration: 4.125 },
    ];
    expect(clipMatchingAudit(clips, 99)).toBe("attack");
    expect(clipMatchingAudit([{ name: "attack", duration: 4.1333 }], 99)).toBe("attack");
    expect(clipMatchingAudit(clips, 49)).toBeNull();
  });
});
