import Link from "next/link";
import type { ActionState, AuditSummary, SampleScore } from "@/api/types";
import { ACTION_STATUS, ACTION_STEP } from "@/pipeline/labels";
import { StatusText } from "./ServerState";
import styles from "./server.module.css";

function Audit({ audit }: { audit: AuditSummary }) {
  return (
    <span className={`pill ${audit.result === "OK" ? "ok" : "bad"}`}>
      {audit.result === "OK" ? "✓" : "✕"} {audit.result} · {audit.score.toFixed(2)}
    </span>
  );
}

/** Audit score, and how far the hands moved: a sample that stood still can have a clean audit. */
function sampleText(s: SampleScore): string {
  return `score ${s.score.toFixed(2)}` + (s.moved == null ? "" : `, hands moved ${s.moved.toFixed(2)} m`);
}

/** One action: library or AI, where it is, its best sample, audit and approval, and a link to review it. */
export function ActionCard({ characterId, action }: { characterId: string; action: ActionState }) {
  const st = ACTION_STATUS[action.status];
  const sources = action.review_sources ?? [];
  return (
    <article className={styles.card} aria-labelledby={`action-${action.name}`}>
      <h3 id={`action-${action.name}`}>
        <span>{action.name}</span>
        <span className="pill">{action.kind === "ai" ? "AI" : "library"}</span>
      </h3>
      <StatusText {...st} text={`${ACTION_STEP[action.step]}: ${st.text}`} />
      <p className="muted" style={{ margin: 0, fontSize: 13 }}>
        {action.detail}
      </p>
      <dl>
        {action.best && (
          <>
            <dt>{action.picked === "by hand" ? "sample (by hand)" : "best sample"}</dt>
            <dd>
              {action.best.name} · {sampleText(action.best)}
              {action.samples && action.samples.length > 1 && (
                <span className="muted"> (all: {action.samples.map((s) => `${s.name} ${sampleText(s)}`).join(", ")})</span>
              )}
            </dd>
          </>
        )}
        {action.audit && (
          <>
            <dt>{action.audit.source}</dt>
            <dd>
              <Audit audit={action.audit} />
            </dd>
          </>
        )}
        {action.merged_audit && (
          <>
            <dt>after merge</dt>
            <dd>
              <Audit audit={action.merged_audit} />
            </dd>
          </>
        )}
        <dt>approved</dt>
        <dd>
          {action.approved
            ? `✓ ${action.approved.date ?? "(no date)"} · score ${action.approved.score.toFixed(2)}`
            : action.kind === "ai"
              ? "not yet"
              : "library clip (no verdict)"}
        </dd>
        <dt>loop</dt>
        <dd>{action.loop ? "yes" : "no (one-shot)"}</dd>
      </dl>
      {sources.length > 0 && (
        <div className={styles.row}>
          {sources.map((source) => (
            <Link key={source} href={{ pathname: "/review/", query: { character: characterId, action: action.name, source } }}>
              {source === "choice" ? "Watch the best sample" : "Watch after merge"}
              {action.gate?.kind === "motion" && source === "choice" ? " and decide" : ""} →
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}
