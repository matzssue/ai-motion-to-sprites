"use client";

import { useRef } from "react";
import { formatLimit, formatShare, formatValue } from "@/audit/metrics";
import { nearestSampleIndex } from "@/audit/tracks";
import { focusMetric, useReview } from "@/state/store";
import { usePlayheadEffect } from "@/state/usePlayheadEffect";
import styles from "./MetricTable.module.css";

/** Every metric with data: value at the playhead, clip maximum, limit, share of samples over the limit. */
export function MetricTable() {
  const audit = useReview((s) => s.audit);
  const selected = useReview((s) => s.selectedMetric);
  const nowCells = useRef(new Map<string, HTMLTableCellElement>());
  const hasSamples = Boolean(audit?.samples);

  usePlayheadEffect((frame) => {
    if (!audit?.samples) return;
    for (const track of audit.tracks) {
      const cell = nowCells.current.get(track.key);
      const value = track.values[nearestSampleIndex(track.times, frame)];
      if (cell) {
        cell.textContent = formatValue(track.key, value);
        cell.classList.toggle(styles.over ?? "over",track.limit !== null && (value ?? 0) > track.limit);
      }
    }
  });

  if (!audit) return <p className="muted">Drop audit.json to see the numbers.</p>;
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>metric</th>
            {hasSamples && <th>at playhead</th>}
            <th>max</th>
            <th>limit</th>
            <th>share of clip</th>
          </tr>
        </thead>
        <tbody>
          {audit.tracks.map((track) => (
            <tr key={track.key} className={track.key === selected ? styles.selected : undefined}>
              <td>
                <button
                  type="button"
                  className={track.error ? `${styles.name} ${styles.bad}` : styles.name}
                  onClick={() => focusMetric(track.key, track.error ? track.error.at_frame : null)}
                >
                  {track.label}
                </button>
              </td>
              {hasSamples && (
                <td
                  ref={(cell) => {
                    if (cell) nowCells.current.set(track.key, cell);
                    else nowCells.current.delete(track.key);
                  }}
                />
              )}
              <td className={track.error ? styles.bad : undefined}>{formatValue(track.key, track.max)}</td>
              <td>{formatLimit(track)}</td>
              <td>{track.error ? formatShare(track.error.share) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
