import { describe, expect, it } from "vitest";
import type { JobSummary } from "@/api/types";
import { gateOfStopLine, runEndText } from "@/pipeline/labels";
import { MAX_SHOWN, emptyLog, isActive, runLogReducer } from "./log";

const job = (state: JobSummary["state"], id = "j1"): JobSummary => ({
  id,
  character_id: "c",
  state,
  created_at: "2026-11-19T10:00:00+00:00",
  line_count: 0,
  samples: {},
});

describe("runLogReducer", () => {
  it("appends lines once, in order, across a reconnect that resends them", () => {
    let s = runLogReducer(emptyLog, { type: "attach", job: job("running") });
    s = runLogReducer(s, { type: "lines", lines: [{ n: 0, text: "a" }, { n: 1, text: "b" }] });
    s = runLogReducer(s, { type: "reconnecting" });
    expect(s.reconnecting).toBe(true);
    s = runLogReducer(s, { type: "lines", lines: [{ n: 2, text: "c" }, { n: 1, text: "b" }] });
    expect(s.lines.map((l) => l.text)).toEqual(["a", "b", "c"]);
    expect(s.next).toBe(3);
    expect(s.reconnecting).toBe(false);
  });

  it("starts empty for another job and keeps the log when the same job is attached again", () => {
    let s = runLogReducer(emptyLog, { type: "attach", job: job("running") });
    s = runLogReducer(s, { type: "lines", lines: [{ n: 0, text: "a" }] });
    expect(runLogReducer(s, { type: "attach", job: job("running") }).lines).toHaveLength(1);
    expect(runLogReducer(s, { type: "attach", job: job("queued", "j2") }).lines).toHaveLength(0);
  });

  it("keeps only the last lines", () => {
    const lines = Array.from({ length: MAX_SHOWN + 10 }, (_, n) => ({ n, text: String(n) }));
    const s = runLogReducer(runLogReducer(emptyLog, { type: "attach", job: job("running") }), { type: "lines", lines });
    expect(s.lines).toHaveLength(MAX_SHOWN);
    expect(s.lines[0]?.n).toBe(10);
  });

  it("ends, and a late reconnect does not reopen it", () => {
    let s = runLogReducer(emptyLog, { type: "attach", job: job("running") });
    s = runLogReducer(s, { type: "end", job: job("waiting_for_review") });
    expect(s.ended && !isActive(s.job)).toBe(true);
    expect(runLogReducer(s, { type: "reconnecting" }).reconnecting).toBe(false);
  });
});

describe("run end text", () => {
  it("names the gate from character.py's STOP line", () => {
    expect(gateOfStopLine("STOP: new AI rig. Look at rig_ai_preview_*.png")).toBe("review the AI rig");
    expect(gateOfStopLine("STOP: action 'attack': key poses (fr. 0,22,48) on sample body_s0")).toBe("review key poses");
    expect(gateOfStopLine("STOP: action 'attack': best sample kf_s1.bvh, score 6.21")).toBe("approve the motion");
    expect(gateOfStopLine("STOP: audit FAIL after merging: run 1.06")).toBe("audit failed after merge");
    expect(gateOfStopLine("something else")).toBeNull();
  });

  it("says done, waiting, failed with its exit code, or cancelled", () => {
    expect(runEndText("waiting_for_review", 2, "STOP: action 'a': key poses (fr. 0)")).toBe(
      "Stopped at gate: review key poses. Waiting for review.",
    );
    expect(runEndText("failed", 1, "SystemExit: step auto_rig.py failed")).toBe("Failed (exit code 1): SystemExit: step auto_rig.py failed");
    expect(runEndText("done", 0, "DONE")).toMatch(/^Done/);
    expect(runEndText("cancelled", null, null)).toBe("Cancelled.");
  });
});
