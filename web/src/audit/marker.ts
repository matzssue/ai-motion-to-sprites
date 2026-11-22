import type { AuditReport, AuditSample, BlenderPoint } from "./schema";
import { nearestSampleIndex, sampleValue } from "./tracks";

export type MarkerPoint = { where: BlenderPoint; value: number; side: string | null; frame: number };

/** Where to draw the marker of `key` at `frame`. With samples it follows the sample nearest to the playhead
 *  (hidden where that sample has no point for the metric); without them it stays on the worst point of the error. */
export function markerAt(
  report: AuditReport,
  samples: AuditSample[] | null,
  times: number[],
  key: string,
  frame: number,
): MarkerPoint | null {
  if (samples && samples.length > 0) {
    const row = samples[nearestSampleIndex(times, frame)];
    const where = row?._where[key];
    if (!row || !where) return null;
    return { where, value: sampleValue(row, key), side: row._side[key] ?? null, frame: row.t };
  }
  const error = report.errors[key];
  if (!error?.where) return null;
  return { where: error.where, value: error.max, side: error.side ?? null, frame: error.at_frame };
}
