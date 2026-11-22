// Steps of a verdict: compose (decision + note) -> preview (the service says what would be written) -> confirm ->
// written. Nothing is written before the reviewer confirms the exact change the preview returned.
import type { GateKind, VerdictPlan, VerdictRequest, VerdictResult } from "@/api/types";

export type Decision = VerdictRequest["decision"];

export type VerdictFlow =
  | { step: "compose"; error: string | null }
  | { step: "previewing"; decision: Decision }
  | { step: "confirm"; plan: VerdictPlan }
  | { step: "submitting"; plan: VerdictPlan }
  | { step: "written"; result: VerdictResult };

export type VerdictFlowEvent =
  | { type: "preview"; decision: Decision }
  | { type: "planned"; plan: VerdictPlan }
  | { type: "submit" }
  | { type: "written"; result: VerdictResult }
  | { type: "fail"; error: string }
  | { type: "back" };

export const initialFlow: VerdictFlow = { step: "compose", error: null };

export function verdictFlowReducer(state: VerdictFlow, event: VerdictFlowEvent): VerdictFlow {
  switch (event.type) {
    case "preview":
      // after a written verdict the panel is ready for the next one (the gate may still be open, e.g. after a reject)
      return state.step === "compose" || state.step === "written" ? { step: "previewing", decision: event.decision } : state;
    case "planned":
      return state.step === "previewing" ? { step: "confirm", plan: event.plan } : state;
    case "submit":
      return state.step === "confirm" ? { step: "submitting", plan: state.plan } : state;
    case "written":
      return state.step === "submitting" ? { step: "written", result: event.result } : state;
    case "fail":
      return { step: "compose", error: event.error };
    case "back":
      return initialFlow;
  }
}

/** The request for a decision; a rejection needs a note (the service refuses one without). */
export function buildRequest(
  gate: GateKind,
  action: string | null | undefined,
  decision: Decision,
  note: string,
  extra: { posesGlb?: string | null; reviewer?: string; configSha?: string } = {},
): VerdictRequest | string {
  if (decision === "reject" && !note.trim()) return "Write what is wrong before rejecting.";
  return {
    gate,
    action: gate === "rig" ? null : (action ?? null),
    decision,
    note: note.trim(),
    reviewer: extra.reviewer?.trim() || null,
    poses_glb: gate === "poses" && decision === "approve" ? (extra.posesGlb ?? null) : null,
    expected_config_sha: extra.configSha ?? null,
  };
}

export const GATE_VERB: Record<GateKind, { approve: string; reject: string }> = {
  rig: { approve: "Approve the AI rig", reject: "Reject the AI rig" },
  poses: { approve: "Approve the key poses", reject: "Reject the key poses" },
  motion: { approve: "Approve the motion", reject: "Reject the motion" },
};
