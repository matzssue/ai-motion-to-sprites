"use client";

import { secondsToFrame } from "@/motion/time";
import { auditedAction, useReview } from "@/state/store";
import styles from "./AuditHeader.module.css";

/** Title, audit result and score, per-group scores, and whether the selected action is the audited one. */
export function AuditHeader() {
  const title = useReview((s) => s.title);
  const audit = useReview((s) => s.audit);
  const model = useReview((s) => s.model);
  const actionName = useReview((s) => s.actionName);
  const report = audit?.report;
  const lastSample = audit?.samples?.at(-1)?.t;
  const audited = useReview(auditedAction);
  const clip = model?.clips.find((c) => c.name === actionName);

  return (
    <div className={styles.header}>
      <h1>{title ?? audit?.fileName ?? "Motion review"}</h1>
      {report && (
        <div className={styles.pills}>
          <span className={`pill ${report.result === "OK" ? "ok" : "bad"}`}>
            audit {report.result} · score {report.score.toFixed(2)}
          </span>
          {Object.entries(report.scores).map(([group, score]) => (
            <span key={group} className="pill">
              {group} {score.toFixed(2)}
            </span>
          ))}
          {report.height_m !== undefined && <span className="pill">height {report.height_m.toFixed(2)} m</span>}
          {audit.samples && <span className="pill">{audit.samples.length} samples</span>}
          {!audit.samples && <span className="pill">no audit_samples.json: errors only</span>}
          {report.skeleton && <span className="pill">skeleton {report.skeleton}</span>}
          {Object.keys(report.skipped).length > 0 && (
            <span className="pill" title={Object.entries(report.skipped).map(([k, why]) => `${k}: ${why}`).join("\n")}>
              {Object.keys(report.skipped).length} skipped
            </span>
          )}
        </div>
      )}
      {clip && lastSample !== undefined && audited !== clip.name && (
        <p className={styles.warning}>
          The audit ends at frame {lastSample}, but “{clip.name}” lasts {secondsToFrame(clip.duration).toFixed(2)} frames:
          {audited ? ` the audited action is probably “${audited}”.` : " this may be the wrong GLB for this audit."}
        </p>
      )}
    </div>
  );
}
