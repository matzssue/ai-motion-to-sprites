// Words and symbols for pipeline states. Every status has a glyph and a text, so none is told by colour alone.
import type { ActionState, JobState, StageName, StageStatus } from "@/api/types";

export type Tone = "ok" | "bad" | "warn" | "neutral";

export const STAGE_LABEL: Record<StageName, string> = {
  prepare: "Prepare model",
  rig: "Auto-rig",
  rig_ai: "AI rig",
  calibration: "Calibration",
  ai: "AI actions",
  merge: "Merge + audit",
  preview: "8-way preview",
};

export const STAGE_STATUS: Record<StageStatus, { glyph: string; text: string; tone: Tone }> = {
  up_to_date: { glyph: "✓", text: "up to date", tone: "ok" },
  stale: { glyph: "↻", text: "runs next", tone: "warn" },
  waiting: { glyph: "⏸", text: "waiting for review", tone: "warn" },
  failed: { glyph: "✕", text: "stopped: needs a fix", tone: "bad" },
  blocked: { glyph: "–", text: "not reached", tone: "neutral" },
  skipped: { glyph: "·", text: "not used", tone: "neutral" },
};

export const ACTION_STEP: Record<ActionState["step"], string> = {
  library: "library clip",
  body: "body sample",
  poses: "key poses",
  motion: "motion",
  approved: "approved",
};

export const ACTION_STATUS: Record<ActionState["status"], { glyph: string; text: string; tone: Tone }> = {
  up_to_date: { glyph: "✓", text: "up to date", tone: "ok" },
  stale: { glyph: "↻", text: "runs next", tone: "warn" },
  waiting: { glyph: "⏸", text: "waiting for review", tone: "warn" },
  error: { glyph: "✕", text: "needs a fix", tone: "bad" },
};

export const JOB_STATE: Record<JobState, { glyph: string; text: string; tone: Tone }> = {
  queued: { glyph: "…", text: "queued", tone: "neutral" },
  running: { glyph: "▶", text: "running", tone: "neutral" },
  done: { glyph: "✓", text: "done", tone: "ok" },
  waiting_for_review: { glyph: "⏸", text: "waiting for review", tone: "warn" },
  failed: { glyph: "✕", text: "failed", tone: "bad" },
  cancelled: { glyph: "■", text: "cancelled", tone: "neutral" },
};

/** Which gate a STOP line of character.py names (its wording in stop() calls). */
export function gateOfStopLine(line: string | null | undefined): string | null {
  if (!line) return null;
  if (/new AI rig/i.test(line)) return "review the AI rig";
  if (/key poses/i.test(line)) return "review key poses";
  if (/best sample|Review page/i.test(line)) return "approve the motion";
  if (/calibration FAIL/i.test(line)) return "calibration failed: fix the rig";
  if (/audit FAIL after merging/i.test(line)) return "audit failed after merge";
  if (/no 'key_poses'/i.test(line)) return "add key_poses to the motion file";
  if (/approved motion now scores/i.test(line)) return "the approved motion scores worse";
  return null;
}

/** One sentence for the end of a run. */
export function runEndText(state: JobState, exitCode: number | null | undefined, outcome: string | null | undefined): string {
  switch (state) {
    case "done":
      return "Done: every stage in range finished.";
    case "waiting_for_review": {
      const gate = gateOfStopLine(outcome);
      return gate ? `Stopped at gate: ${gate}. Waiting for review.` : "Stopped at a human gate. Waiting for review.";
    }
    case "failed":
      return `Failed${exitCode === null || exitCode === undefined ? "" : ` (exit code ${exitCode})`}${outcome ? `: ${outcome}` : "."}`;
    case "cancelled":
      return "Cancelled.";
    default:
      return JOB_STATE[state].text;
  }
}
