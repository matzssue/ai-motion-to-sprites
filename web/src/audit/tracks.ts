import { compareMetrics, metricGroup, metricLabel, metricUnit } from "./metrics";
import type { AuditReport, AuditSample, MetricTrack } from "./schema";

/** Keys of a sample row that hold metric values (not `t` and not the `_where` / `_side` / `_loose_fingers` extras). */
function sampleMetricKeys(samples: AuditSample[]): Set<string> {
  const keys = new Set<string>();
  for (const row of samples) {
    for (const [key, value] of Object.entries(row)) {
      if (key !== "t" && !key.startsWith("_") && typeof value === "number") keys.add(key);
    }
  }
  return keys;
}

/** A missing value counts as 0, as `r.get(k, 0)` does in the audit. */
export function sampleValue(row: AuditSample, key: string): number {
  const value = row[key];
  return typeof value === "number" ? value : 0;
}

/** Runs of consecutive samples strictly over the limit (the audit's test is `value > limit`). */
export function failRanges(times: number[], values: number[], limit: number): [number, number][] {
  const ranges: [number, number][] = [];
  let start: number | null = null;
  for (let i = 0; i < values.length; i++) {
    const over = (values[i] ?? 0) > limit;
    if (over && start === null) start = times[i] ?? 0;
    if (!over && start !== null) {
      ranges.push([start, times[i - 1] ?? start]);
      start = null;
    }
  }
  if (start !== null) ranges.push([start, times[times.length - 1] ?? start]);
  return ranges;
}

/** One track per metric that has data (a non-zero value in any sample, a non-zero maximum, or an error) and one per
 *  skipped metric (no values: the skeleton lacks a role it needs). */
export function buildTracks(report: AuditReport, samples: AuditSample[] | null): MetricTrack[] {
  const keys = new Set([...Object.keys(report.maxima), ...Object.keys(report.errors), ...Object.keys(report.skipped)]);
  if (samples) sampleMetricKeys(samples).forEach((k) => keys.add(k));
  const noLimit = new Set(report.no_limit);
  const times = samples ? samples.map((row) => row.t) : [];

  const tracks: MetricTrack[] = [];
  for (const key of [...keys].sort(compareMetrics)) {
    const why = report.skipped[key];
    if (why !== undefined) {
      tracks.push({
        ...describe(key),
        limit: null,
        reportedOnly: false,
        max: 0,
        times: [],
        values: [],
        failRanges: [],
        error: null,
        skipped: why,
      });
      continue;
    }
    const values = samples ? samples.map((row) => sampleValue(row, key)) : [];
    const error = report.errors[key] ?? null;
    const max = Math.max(report.maxima[key] ?? 0, ...values);
    if (max <= 0 && !error) continue;
    const limit = noLimit.has(key) ? null : (report.limits[key] ?? null);
    let ranges: [number, number][] = [];
    if (limit !== null && samples) ranges = failRanges(times, values, limit);
    else if (error) ranges = [error.range];
    tracks.push({
      ...describe(key),
      limit,
      reportedOnly: noLimit.has(key),
      max,
      times,
      values,
      failRanges: ranges,
      error,
      skipped: null,
    });
  }
  return tracks;
}

function describe(key: string) {
  return { key, label: metricLabel(key), group: metricGroup(key), unit: metricUnit(key) };
}

/** Where a click on a failing range jumps: the audit's `at_frame` when it lies in the range, else the range's worst sample. */
export function worstSampleInRange(track: MetricTrack, [from, to]: [number, number]): number {
  const atFrame = track.error?.at_frame;
  if (atFrame !== undefined && atFrame >= from && atFrame <= to) return atFrame;
  let best = from;
  let bestValue = -Infinity;
  track.times.forEach((t, i) => {
    const value = track.values[i] ?? 0;
    if (t >= from && t <= to && value > bestValue) {
      best = t;
      bestValue = value;
    }
  });
  return best;
}

/** Index of the sample closest to `frame` (`times` sorted ascending); -1 when there are no samples. */
export function nearestSampleIndex(times: number[], frame: number): number {
  if (times.length === 0) return -1;
  let lo = 0;
  let hi = times.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if ((times[mid] ?? 0) <= frame) lo = mid;
    else hi = mid;
  }
  return Math.abs((times[hi] ?? 0) - frame) < Math.abs((times[lo] ?? 0) - frame) ? hi : lo;
}
