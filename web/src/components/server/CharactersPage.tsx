"use client";

import Link from "next/link";
import { api } from "@/api/client";
import { useResource } from "@/api/resource";
import { STAGE_LABEL } from "@/pipeline/labels";
import { TopNav } from "../TopNav";
import { Loading, ServerProblem, StatusText } from "./ServerState";
import styles from "./server.module.css";

/** Every character the service was started with, and what each waits for. */
export function CharactersPage() {
  const [list, reload] = useResource("characters", api.characters);
  return (
    <div className={styles.page}>
      <TopNav current="characters" />
      <header className={styles.head}>
        <div>
          <h1>Characters</h1>
          <p className="muted">Which character, which stage is waiting for you.</p>
        </div>
        <button type="button" onClick={reload} disabled={list.loading || list.refreshing}>
          {list.refreshing ? "Refreshing…" : "Refresh"}
        </button>
      </header>
      {list.loading && <Loading what="characters" />}
      {list.error && <ServerProblem error={list.error} onRetry={reload} />}
      {list.data && list.data.length === 0 && <p>The service has no characters. Start it with a character.json or a folder.</p>}
      {list.data && list.data.length > 0 && (
        <ul className={styles.list}>
          {list.data.map((c) => (
            <li key={c.id}>
              <div>
                <h2>
                  <Link href={{ pathname: "/character/", query: { id: c.id } }}>{c.name}</Link>
                </h2>
                <span className="muted" style={{ fontSize: 13, overflowWrap: "anywhere" }}>
                  {c.config_path}
                </span>
              </div>
              <div className={styles.row}>
                {c.active_job && <StatusText glyph="▶" text={`run ${c.active_job.state}`} tone="neutral" />}
                {c.problems && c.problems.length > 0 && <StatusText glyph="✕" text="config problem" tone="bad" />}
                {c.gate ? (
                  <StatusText glyph="⏸" text={`waiting: ${c.gate.title}`} tone="warn" />
                ) : c.done ? (
                  <StatusText glyph="✓" text="done, output up to date" tone="ok" />
                ) : c.stale_stage ? (
                  <StatusText glyph="↻" text={`next run starts at ${STAGE_LABEL[c.stale_stage]}`} tone="warn" />
                ) : (
                  <StatusText glyph="–" text="stopped (see the pipeline)" tone="neutral" />
                )}
                <Link href={{ pathname: "/character/", query: { id: c.id } }}>Open pipeline →</Link>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
