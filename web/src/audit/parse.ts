import { z } from "zod";
import { AuditReportSchema, AuditSamplesSchema, type AuditReport, type AuditSample } from "./schema";

/** A file that is not valid JSON or not in the format motion_audit.py writes. `message` is shown to the user. */
export class AuditFileError extends Error {
  constructor(
    readonly fileName: string,
    readonly reason: string,
  ) {
    super(`${fileName}: ${reason}`);
    this.name = "AuditFileError";
  }
}

export type AuditJsonKind = "report" | "samples" | "review" | "unknown";

const REPORT_KEYS = ["result", "errors", "limits", "maxima"];
const MAX_ISSUES = 4;

export function readJson(fileName: string, text: string): unknown {
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new AuditFileError(fileName, `not valid JSON (${(e as Error).message})`);
  }
}

/** audit.json is an object with `errors`; audit_samples.json is an array of rows with `t`;
 *  a review folder's data.json (review_page.py) carries the report under `audit`. */
export function detectKind(json: unknown): AuditJsonKind {
  if (Array.isArray(json)) return "samples";
  if (json && typeof json === "object") {
    if ("audit" in json && "glb" in json) return "review";
    if (REPORT_KEYS.some((k) => k in json)) return "report";
  }
  return "unknown";
}

export function parseReport(fileName: string, json: unknown): AuditReport {
  const source = detectKind(json) === "review" ? (json as { audit: unknown }).audit : json;
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    throw new AuditFileError(fileName, "expected the audit.json object written by motion_audit.py");
  }
  const missing = REPORT_KEYS.filter((k) => !(k in source));
  if (missing.length === REPORT_KEYS.length) {
    throw new AuditFileError(fileName, "this is not a motion_audit.py report (no result, errors, limits or maxima)");
  }
  if (missing.length > 0) {
    throw new AuditFileError(fileName, `missing ${missing.join(", ")}: written by an older or different audit script?`);
  }
  const parsed = AuditReportSchema.safeParse(source);
  if (!parsed.success) throw new AuditFileError(fileName, describeIssues(parsed.error));
  return parsed.data;
}

export function parseSamples(fileName: string, json: unknown): AuditSample[] {
  if (!Array.isArray(json)) {
    throw new AuditFileError(fileName, "expected audit_samples.json: an array of rows with `t` in frames");
  }
  const parsed = AuditSamplesSchema.safeParse(json);
  if (!parsed.success) throw new AuditFileError(fileName, describeIssues(parsed.error));
  return [...parsed.data].sort((a, b) => a.t - b.t);
}

function describeIssues(error: z.ZodError): string {
  const lines = error.issues.slice(0, MAX_ISSUES).map((issue) => {
    const path = issue.path.length ? issue.path.join(".") : "(top level)";
    return `${path}: ${issue.message}`;
  });
  const more = error.issues.length - lines.length;
  return `unexpected format - ${lines.join("; ")}${more > 0 ? ` (and ${more} more)` : ""}`;
}
