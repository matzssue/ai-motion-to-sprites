// Shapes of the files written by pipeline/checks/motion_audit.py, validated at runtime with zod.
// Every TypeScript type for audit data comes from here.
import { z } from "zod";

/** A point in Blender world space (Z up, metres). Convert with `blenderToThree` before drawing. */
export const BlenderPointSchema = z.tuple([z.number(), z.number(), z.number()]);

export const AuditErrorSchema = z.object({
  limit: z.number(),
  max: z.number(),
  at_frame: z.number(),
  samples: z.number().int().optional(),
  share: z.number(),
  range: z.tuple([z.number(), z.number()]),
  where: BlenderPointSchema.nullable().optional(),
  side: z.string().nullable().optional(),
  area: z.number().optional(),
});

export const AuditReportSchema = z.object({
  result: z.enum(["OK", "FAIL"]),
  score: z.number(),
  scores: z.record(z.string(), z.number()).default({}),
  score_area: z.number().optional(),
  height_m: z.number().optional(),
  errors: z.record(z.string(), AuditErrorSchema),
  maxima: z.record(z.string(), z.number()),
  rest: z.record(z.string(), z.number()).optional(),
  limits: z.record(z.string(), z.number()),
  no_limit: z.array(z.string()).default([]),
  frames: z.array(z.number()).nullable().optional(),
  /** skeleton profile the audit used (absent in reports from before profiles: Mixamo) */
  skeleton: z.string().optional(),
  /** metric -> why it was not measured (a role the skeleton does not have); never scored */
  skipped: z.record(z.string(), z.string()).default({}),
});

/** One row of audit_samples.json: `t` in Blender frames, then one number per measured metric. */
export const AuditSampleSchema = z
  .object({
    t: z.number(),
    _where: z.record(z.string(), BlenderPointSchema).default({}),
    _side: z.record(z.string(), z.string()).default({}),
  })
  .catchall(z.unknown());

export const AuditSamplesSchema = z.array(AuditSampleSchema).min(1);

export type BlenderPoint = z.infer<typeof BlenderPointSchema>;
export type AuditError = z.infer<typeof AuditErrorSchema>;
export type AuditReport = z.infer<typeof AuditReportSchema>;
export type AuditSample = z.infer<typeof AuditSampleSchema>;

export type MetricGroup = "penetration" | "joints" | "smoothness" | "grip" | "feet" | "other";
export type MetricUnit = "cm" | "deg" | "percent";

/** One timeline row: a metric's value at every sample against its limit. */
export type MetricTrack = {
  key: string;
  label: string;
  group: MetricGroup;
  unit: MetricUnit;
  /** null when the audit has no limit for it */
  limit: number | null;
  /** listed in `no_limit`: measured for information, never decides OK */
  reportedOnly: boolean;
  max: number;
  times: number[];
  values: number[];
  /** runs of consecutive samples over the limit, as [first t, last t] in frames */
  failRanges: [number, number][];
  error: AuditError | null;
  /** why the audit did not measure it (no values, no limit), or null */
  skipped: string | null;
};
