// Names for the generated contract (schema.d.ts, from the service's OpenAPI document). Aliases only: every shape
// comes from the service's Pydantic models, so a change there shows up here as a type error.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ActionState = Schemas["ActionState"];
export type AuditSummary = Schemas["AuditSummary"];
export type Change = Schemas["Change"];
export type CharacterSummary = Schemas["CharacterSummary"];
export type Gate = Schemas["Gate"];
export type Health = Schemas["Health"];
export type JobSummary = Schemas["JobSummary"];
export type Manifest = Schemas["Manifest"];
export type PipelineState = Schemas["PipelineState"];
export type RunRequest = Schemas["RunRequest"];
export type StageState = Schemas["StageState"];
export type TrailEntry = Schemas["TrailEntry"];
export type VerdictPlan = Schemas["VerdictPlan"];
export type VerdictRequest = Schemas["VerdictRequest"];
export type VerdictResult = Schemas["VerdictResult"];

export type StageName = StageState["name"];
export type StageStatus = StageState["status"];
export type JobState = JobSummary["state"];
export type GateKind = Gate["kind"];
export type ReviewSource = ActionState["review_sources"][number];

export const STAGES: readonly StageName[] = ["prepare", "rig", "rig_ai", "calibration", "ai", "merge", "preview"];
