"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, urls } from "@/api/client";
import { useResource } from "@/api/resource";
import type { ReviewSource, VerdictResult } from "@/api/types";
import { loadFromUrl, loadIntoReview } from "@/loading/load";
import { ACTION_STATUS, ACTION_STEP } from "@/pipeline/labels";
import { resetReview, useReview } from "@/state/store";
import { AuditHeader } from "../AuditHeader";
import { TopNav } from "../TopNav";
import { useKeyboard } from "../useKeyboard";
import { ViewerWorkspace } from "../ViewerWorkspace";
import { Loading, ServerProblem, StatusText } from "./ServerState";
import styles from "./server.module.css";
import { VerdictHistory, VerdictPanel, VerdictWritten } from "./VerdictPanel";

/** The 2a viewer fed by the service's manifest for one action, with the verdict controls and the action's trail. */
export function ActionReviewPage() {
  const params = useSearchParams();
  const cid = params.get("character");
  const action = params.get("action");
  const wanted = params.get("source") as ReviewSource | null;
  const [state, reload] = useResource(cid ? `character:${cid}` : null, (signal) => api.character(cid!, signal));
  const [history, reloadHistory] = useResource(cid && action ? `history:${cid}:${action}` : null, (signal) =>
    api.verdicts(cid!, action!, signal),
  );
  const [written, setWritten] = useState<VerdictResult | null>(null);
  const loading = useReview((s) => s.loading);
  const problems = useReview((s) => s.problems);
  const model = useReview((s) => s.model);
  useKeyboard();

  const act = state.data?.actions.find((a) => a.name === action) ?? null;
  const sources = act?.review_sources ?? [];
  const source: ReviewSource | null = wanted && sources.includes(wanted) ? wanted : (sources[0] ?? null);
  const manifest = cid && action && source ? urls.manifest(cid, action, source) : null;

  useEffect(() => {
    resetReview();
    if (manifest) void loadIntoReview(loadFromUrl(manifest));
    return resetReview;
  }, [manifest]);

  if (!cid || !action) {
    return (
      <div className={styles.page}>
        <TopNav />
        <p>
          The address needs <code>?character=…&amp;action=…</code>. Pick an action on the <Link href="/characters/">characters page</Link>.
        </p>
      </div>
    );
  }

  const gate = act?.gate?.kind === "motion" ? act.gate : null;
  return (
    <div className={styles.page}>
      <TopNav />
      <header className={styles.head}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <Link href={{ pathname: "/character/", query: { id: cid } }}>← {state.data?.character.name ?? cid} pipeline</Link>
          <AuditHeader />
        </div>
        {sources.length > 1 && (
          <nav className={styles.row} aria-label="Which GLB and audit">
            {sources.map((s) => (
              <Link
                key={s}
                href={{ pathname: "/review/", query: { character: cid, action, source: s } }}
                aria-current={s === source ? "page" : undefined}
              >
                {s === "choice" ? "best sample" : "after merge"}
              </Link>
            ))}
          </nav>
        )}
      </header>
      {state.loading && <Loading what="the action" />}
      {state.error && <ServerProblem error={state.error} onRetry={reload} />}
      {state.data && !act && <p role="alert">No action “{action}” in this character.</p>}
      {act && sources.length === 0 && <p>Nothing to watch yet: “{action}” has no chosen sample or merged audit. {act.detail}.</p>}
      {loading && <p className="muted">Loading the motion…</p>}
      {problems.length > 0 && (
        <ul className={styles.error} role="alert" style={{ margin: 0, paddingLeft: 30 }}>
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
      {act && state.data && (model || sources.length > 0) && (
        <ViewerWorkspace
          side={
            <>
              {written && <VerdictWritten result={written} />}
              <section className={styles.verdict} aria-labelledby="action-state">
                <h2 id="action-state">{action}</h2>
                <StatusText {...ACTION_STATUS[act.status]} text={`${ACTION_STEP[act.step]}: ${ACTION_STATUS[act.status].text}`} />
                <p className="muted" style={{ margin: 0, fontSize: 13 }}>
                  {gate ? gate.needs : act.detail}
                </p>
                {act.approved && (
                  <p style={{ margin: 0 }}>
                    ✓ Approved {act.approved.date ?? ""} with score {act.approved.score.toFixed(2)}
                  </p>
                )}
                {source === "merged" && gate && <p className={styles.warn}>This is the merged GLB; the verdict is about the best sample.</p>}
              </section>
              {gate && (
                <VerdictPanel
                  key={state.data.config_sha}
                  characterId={cid}
                  gate={gate}
                  configSha={state.data.config_sha}
                  onWritten={(r) => {
                    setWritten(r);
                    reload();
                    reloadHistory();
                  }}
                />
              )}
              <section className={styles.verdict} aria-labelledby="history-title">
                <h3 id="history-title">Verdicts on “{action}”</h3>
                {history.data ? <VerdictHistory entries={history.data} /> : <Loading what="the trail" />}
              </section>
            </>
          }
        />
      )}
    </div>
  );
}
