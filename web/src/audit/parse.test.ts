import { describe, expect, it } from "vitest";
import { REPORT } from "./fixtures";
import { AuditFileError, detectKind, parseReport, parseSamples, readJson } from "./parse";

function caught(fn: () => unknown): AuditFileError {
  try {
    fn();
  } catch (e) {
    if (e instanceof AuditFileError) return e;
    throw e;
  }
  throw new Error("expected an AuditFileError");
}

describe("audit parsing", () => {
  it("accepts a motion_audit.py report", () => {
    const report = parseReport("audit.json", REPORT);
    expect(report.result).toBe("FAIL");
    expect(report.errors.hands_in_head?.where).toEqual([-0.055, -0.241, 0.5615]);
  });

  it("takes the report out of a review folder's data.json", () => {
    const report = parseReport("data.json", { title: "x", glb: "E:/a.glb", frames: 50, audit: REPORT });
    expect(report.score).toBe(1.4);
  });

  it("fills defaults for fields older reports lack", () => {
    const older: Record<string, unknown> = { ...REPORT };
    delete older.scores;
    delete older.no_limit;
    const report = parseReport("audit.json", older);
    expect(report.scores).toEqual({});
    expect(report.no_limit).toEqual([]);
  });

  it("explains a file from another tool", () => {
    const e = caught(() => parseReport("audit.json", { intersections: 0, sampled_poses: 12 }));
    expect(e.message).toBe("audit.json: this is not a motion_audit.py report (no result, errors, limits or maxima)");
  });

  it("names the missing fields of an incomplete report", () => {
    const partial: Record<string, unknown> = { ...REPORT };
    delete partial.limits;
    delete partial.maxima;
    expect(caught(() => parseReport("audit.json", partial)).reason).toMatch(/^missing limits, maxima/);
  });

  it("points at the wrong value", () => {
    const bad = { ...REPORT, errors: { hands_in_head: { ...REPORT.errors.hands_in_head, max: "big" } } };
    expect(caught(() => parseReport("audit.json", bad)).reason).toMatch(/errors\.hands_in_head\.max/);
  });

  it("reports invalid JSON with the file name", () => {
    expect(caught(() => readJson("audit.json", "{ nope")).message).toMatch(/^audit\.json: not valid JSON/);
  });

  it("parses samples sorted by t, with empty extras by default", () => {
    const rows = parseSamples("audit_samples.json", [
      { t: 0.25, hands_in_head: 0.001 },
      { t: 0, stretch: 0.1, _where: { stretch: [1, 2, 3] } },
    ]);
    expect(rows.map((r) => r.t)).toEqual([0, 0.25]);
    expect(rows[1]?._where).toEqual({});
    expect(rows[0]?._where).toEqual({ stretch: [1, 2, 3] });
  });

  it("rejects samples that are not rows with t", () => {
    expect(caught(() => parseSamples("s.json", [{ time: 1 }])).reason).toMatch(/0\.t/);
    expect(caught(() => parseSamples("s.json", REPORT)).reason).toMatch(/array of rows/);
  });

  it("tells the three JSON files apart", () => {
    expect(detectKind(REPORT)).toBe("report");
    expect(detectKind([{ t: 0 }])).toBe("samples");
    expect(detectKind({ glb: "a.glb", audit: REPORT })).toBe("review");
    expect(detectKind({ glb: "a.glb" })).toBe("unknown");
    expect(detectKind(3)).toBe("unknown");
  });
});
