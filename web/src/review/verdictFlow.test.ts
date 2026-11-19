import { describe, expect, it } from "vitest";
import type { VerdictPlan, VerdictResult } from "@/api/types";
import { buildRequest, initialFlow, verdictFlowReducer } from "./verdictFlow";

const request = { gate: "motion" as const, action: "attack", decision: "approve" as const, note: "" };
const plan: VerdictPlan = { request, changes: [], summary: "approve", config_sha: "abc" };
const result: VerdictResult = {
  summary: "approve",
  entry: { id: "1", at: "2026-11-19T10:00:00+00:00", reviewer: "me", gate: "motion", decision: "approve", note: "", changes: [] },
};

describe("verdictFlowReducer", () => {
  it("only writes after a preview and a confirmation", () => {
    let s = verdictFlowReducer(initialFlow, { type: "submit" });
    expect(s.step).toBe("compose");
    s = verdictFlowReducer(s, { type: "preview", decision: "approve" });
    expect(verdictFlowReducer(s, { type: "submit" }).step).toBe("previewing");
    s = verdictFlowReducer(s, { type: "planned", plan });
    expect(s.step).toBe("confirm");
    s = verdictFlowReducer(s, { type: "submit" });
    expect(s).toEqual({ step: "submitting", plan });
    s = verdictFlowReducer(s, { type: "written", result });
    expect(s.step).toBe("written");
  });

  it("starts a new verdict after a written one", () => {
    expect(verdictFlowReducer({ step: "written", result }, { type: "preview", decision: "approve" }).step).toBe("previewing");
  });

  it("goes back to composing with the error", () => {
    const s = verdictFlowReducer({ step: "submitting", plan }, { type: "fail", error: "409: changed" });
    expect(s).toEqual({ step: "compose", error: "409: changed" });
  });
});

describe("buildRequest", () => {
  it("needs a note to reject", () => {
    expect(buildRequest("motion", "attack", "reject", "  ")).toBe("Write what is wrong before rejecting.");
  });

  it("sends the action, the poses GLB only for approving poses, and the config hash", () => {
    expect(buildRequest("poses", "attack", "approve", " ok ", { posesGlb: "poses_v2/poses.glb", configSha: "x" })).toEqual({
      gate: "poses",
      action: "attack",
      decision: "approve",
      note: "ok",
      reviewer: null,
      poses_glb: "poses_v2/poses.glb",
      expected_config_sha: "x",
    });
    expect(buildRequest("rig", "attack", "reject", "thumb", { posesGlb: "x" })).toMatchObject({ action: null, poses_glb: null });
  });
});
