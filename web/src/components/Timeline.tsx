"use client";

import { Fragment, useRef, type PointerEvent } from "react";
import { formatLimit, GROUPS } from "@/audit/metrics";
import type { MetricTrack } from "@/audit/schema";
import { worstSampleInRange } from "@/audit/tracks";
import { QUARTER_FRAME, snapToQuarter } from "@/motion/time";
import { currentEndFrame, focusMetric, seek, useReview, type LoadedAudit } from "@/state/store";
import { usePlayheadEffect } from "@/state/usePlayheadEffect";
import styles from "./Timeline.module.css";

const WIDTH = 1000;
const HEIGHT = 30;

/** Frames shown on the x axis: the clip, stretched when the audit runs longer (a wrong action is then visible). */
function domainOf(audit: LoadedAudit, clipEnd: number): number {
  const auditEnd = Math.max(
    audit.samples?.at(-1)?.t ?? 0,
    ...Object.values(audit.report.errors).map((e) => e.range[1]),
  );
  return Math.max(clipEnd, auditEnd, 1);
}

function tickStep(domain: number): number {
  return [1, 2, 5, 10, 20, 50, 100].find((s) => domain / s <= 12) ?? 200;
}

function frameAtPointer(e: PointerEvent<HTMLElement>, domain: number): number {
  const box = e.currentTarget.getBoundingClientRect();
  const ratio = Math.min(Math.max((e.clientX - box.left) / box.width, 0), 1);
  return snapToQuarter(ratio * domain);
}

export function Timeline() {
  const audit = useReview((s) => s.audit);
  const clipEnd = useReview(currentEndFrame);
  const selected = useReview((s) => s.selectedMetric);
  const cursor = useRef<HTMLDivElement>(null);
  const domain = audit ? domainOf(audit, clipEnd) : 1;

  usePlayheadEffect((frame) => {
    if (cursor.current) cursor.current.style.left = `${(100 * frame) / domain}%`;
  });

  if (!audit) return null;
  if (audit.tracks.length === 0) return <p className="muted">Every metric is 0 in this audit.</p>;

  function scrub(e: PointerEvent<HTMLDivElement>) {
    if (e.buttons !== 1) return;
    useReview.setState({ playing: false });
    seek(frameAtPointer(e, domain));
  }

  const ticks: number[] = [];
  for (let f = 0; f <= domain; f += tickStep(domain)) ticks.push(f);

  return (
    <section className={styles.timeline} aria-label="Audit timeline">
      <div className={styles.grid}>
        <div />
        <div className={styles.ruler}>
          {ticks.map((f) => (
            <span key={f} style={{ left: `${(100 * f) / domain}%` }}>
              {f}
            </span>
          ))}
        </div>
        {GROUPS.map((group) => {
          const tracks = audit.tracks.filter((t) => t.group === group);
          if (tracks.length === 0) return null;
          const score = audit.report.scores[group];
          return (
            <Fragment key={group}>
              <div className={styles.groupName}>
                {group}
                {score !== undefined && <span className={styles.groupScore}> {score.toFixed(2)}</span>}
              </div>
              <div className={styles.groupRule} />
              {tracks.map((track) => (
                <TrackRow
                  key={track.key}
                  track={track}
                  domain={domain}
                  selected={track.key === selected}
                  onScrub={scrub}
                />
              ))}
            </Fragment>
          );
        })}
        <div className={styles.cursorLayer} aria-hidden>
          <div ref={cursor} className={styles.cursor} />
        </div>
      </div>
    </section>
  );
}

type TrackRowProps = {
  track: MetricTrack;
  domain: number;
  selected: boolean;
  onScrub: (e: PointerEvent<HTMLDivElement>) => void;
};

function TrackRow({ track, domain, selected, onScrub }: TrackRowProps) {
  const top = Math.max(track.max, track.limit ?? 0) * 1.1 || 1;
  const x = (frame: number) => (WIDTH * frame) / domain;
  const y = (value: number) => HEIGHT - 2 - ((HEIGHT - 4) * value) / top;
  const points = track.times.map((t, i) => `${x(t).toFixed(1)},${y(track.values[i] ?? 0).toFixed(1)}`).join(" ");
  const jumpTo = track.error ? track.error.at_frame : null;
  const title = track.limit === null ? formatLimit(track) : `limit ${formatLimit(track)}`;

  return (
    <>
      <button
        type="button"
        className={`${styles.label} ${track.error ? styles.failing : ""} ${selected ? styles.selected : ""}`}
        onClick={() => focusMetric(track.key, jumpTo)}
        title={track.error ? `jump to frame ${track.error.at_frame}` : "show this metric in 3D"}
      >
        {track.label}
        {track.limit === null && <span className={styles.reported}> · {formatLimit(track)}</span>}
      </button>
      <div
        className={styles.plot}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          onScrub(e);
        }}
        onPointerMove={onScrub}
      >
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label={`${track.label}, ${title}`}>
          {track.failRanges.map((range) => (
            <rect
              key={range[0]}
              className={styles.fail}
              x={x(range[0] - QUARTER_FRAME / 2)}
              width={Math.max(x(range[1] - range[0] + QUARTER_FRAME), 2)}
              y={0}
              height={HEIGHT}
              onPointerDown={(e) => {
                e.stopPropagation();
                focusMetric(track.key, worstSampleInRange(track, range));
              }}
            >
              <title>{`fr. ${range[0]}–${range[1]}: over the ${title}. Click to jump.`}</title>
            </rect>
          ))}
          {track.limit !== null && (
            <line className={styles.limit} x1={0} x2={WIDTH} y1={y(track.limit)} y2={y(track.limit)} />
          )}
          {points && (
            <polyline className={track.limit === null ? styles.lineMuted : styles.line} points={points} />
          )}
        </svg>
      </div>
    </>
  );
}
