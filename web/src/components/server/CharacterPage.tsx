"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { api } from "@/api/client";
import { useResource } from "@/api/resource";
import type { VerdictResult } from "@/api/types";
import { TopNav } from "../TopNav";
import { ActionCard } from "./ActionCard";
import { GateCallout } from "./GateCallout";
import { RunControl } from "./RunControl";
import { Loading, ServerProblem } from "./ServerState";
import { StageStepper } from "./StageStepper";
import styles from "./server.module.css";
import { VerdictHistory, VerdictWritten } from "./VerdictPanel";

/** One character's pipeline: stages, the waiting gate, actions, runs and the verdict trail. */
export function CharacterPage() {
  const id = useSearchParams().get("id");
  const [state, reload] = useResource(id ? `character:${id}` : null, (signal) => api.character(id!, signal));
  const [history, reloadHistory] = useResource(id ? `history:${id}` : null, (signal) => api.verdicts(id!, undefined, signal));
  const [written, setWritten] = useState<VerdictResult | null>(null);
  const data = state.data;

  function refresh() {
    reload();
    reloadHistory();
  }

  return (
    <div className={styles.page}>
      <TopNav current="characters" />
      {!id ? (
        <p>
          No character in the address. Pick one on the <Link href="/characters/">characters page</Link>.
        </p>
      ) : (
        <>
          <header className={styles.head}>
            <div>
              <h1>{data?.character.name ?? id}</h1>
              {data && (
                <p className="muted" style={{ fontSize: 13, overflowWrap: "anywhere" }}>
                  {data.character.config_path} · work dir {data.character.work_dir ?? "?"}
                </p>
              )}
            </div>
            <button type="button" onClick={refresh} disabled={state.loading || state.refreshing}>
              {state.refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </header>
          {state.loading && <Loading what="the pipeline state" />}
          {state.error && <ServerProblem error={state.error} onRetry={refresh} />}
          {data && (
            <>
              {(data.character.problems ?? []).length > 0 && (
                <ul className={styles.error} role="alert" style={{ margin: 0, paddingLeft: 30 }}>
                  {data.character.problems!.map((p) => (
                    <li key={p} style={{ whiteSpace: "pre-wrap" }}>
                      {p}
                    </li>
                  ))}
                </ul>
              )}
              {written && <VerdictWritten result={written} />}
              {data.character.gate && (
                <GateCallout
                  characterId={data.character.id}
                  gate={data.character.gate}
                  configSha={data.config_sha}
                  onWritten={(r) => {
                    setWritten(r);
                    refresh();
                  }}
                />
              )}
              {!data.character.gate && data.character.done && (
                <p className={`${styles.end} ${styles.ok}`}>✓ Done: every stage is up to date and the output GLB is current.</p>
              )}
              <section className={styles.section} aria-labelledby="stages-title">
                <h2 id="stages-title">Pipeline</h2>
                <StageStepper stages={data.stages} />
              </section>
              <section className={styles.section} aria-labelledby="actions-title">
                <h2 id="actions-title">Actions</h2>
                <div className={styles.cards}>
                  {data.actions.map((a) => (
                    <ActionCard key={a.name} characterId={data.character.id} action={a} />
                  ))}
                </div>
              </section>
              <RunControl characterId={data.character.id} activeJob={data.character.active_job} onEnded={refresh} />
              <section className={styles.section} aria-labelledby="trail-title">
                <h2 id="trail-title">Review trail</h2>
                {history.data ? <VerdictHistory entries={history.data} /> : history.loading ? <Loading what="the trail" /> : null}
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
