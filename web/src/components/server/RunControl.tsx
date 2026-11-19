"use client";

import { useEffect, useId, useRef, useState } from "react";
import { api } from "@/api/client";
import { useResource } from "@/api/resource";
import { STAGES, type JobSummary, type StageName } from "@/api/types";
import { JOB_STATE, STAGE_LABEL, runEndText } from "@/pipeline/labels";
import { isActive } from "@/runs/log";
import { useRunLog } from "@/runs/useRunLog";
import { StatusText } from "./ServerState";
import styles from "./server.module.css";

/** Start a pipeline run for this character (optional stage range), follow its log, cancel it, see how it ended. */
export function RunControl({
  characterId,
  activeJob,
  onEnded,
}: {
  characterId: string;
  activeJob: JobSummary | null | undefined;
  onEnded: (job: JobSummary) => void;
}) {
  const id = useId();
  const [from, setFrom] = useState<StageName | "">("");
  const [to, setTo] = useState<StageName>("preview");
  const [error, setError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [health] = useResource("health", api.health);
  const { log, attach } = useRunLog(onEnded);
  const pre = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (activeJob) attach(activeJob);
  }, [activeJob, attach]);

  useEffect(() => {
    if (follow && pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [log.lines.length, follow]);

  const job = log.job;
  const running = isActive(job);
  const rangeBad = from !== "" && STAGES.indexOf(from) > STAGES.indexOf(to);

  async function start() {
    setError(null);
    try {
      attach(await api.startRun(characterId, { from_stage: from || null, to_stage: to }));
      setFollow(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      await api.cancelJob(job.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const command = health.data?.pipeline_command;
  return (
    <section className={styles.run} aria-labelledby={`${id}-run`}>
      <h2 id={`${id}-run`} style={{ margin: 0, fontSize: 17 }}>
        Run the pipeline
      </h2>
      {command && (
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          Runs <code>{command.map((c) => c.split(/[\\/]/).at(-1)).join(" ")}</code> --character … (set when the service started).
          {command.some((c) => c.endsWith("fake_pipeline.py")) && " This is the fake pipeline: it writes nothing."}
        </p>
      )}
      <div className={styles.row}>
        <label>
          From
          <select value={from} onChange={(e) => setFrom(e.target.value as StageName | "")} disabled={running}>
            <option value="">first stage that is not up to date</option>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {s} (forces {STAGE_LABEL[s]} and later)
              </option>
            ))}
          </select>
        </label>
        <label>
          To
          <select value={to} onChange={(e) => setTo(e.target.value as StageName)} disabled={running}>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className={styles.primary} onClick={start} disabled={running || rangeBad}>
          Start run
        </button>
        <button type="button" className={styles.danger} onClick={cancel} disabled={!running}>
          Cancel run
        </button>
      </div>
      {rangeBad && (
        <p className={styles.bad} role="alert" style={{ margin: 0 }}>
          “From” comes after “To”.
        </p>
      )}
      {error && (
        <p className={styles.bad} role="alert" style={{ margin: 0 }}>
          {error}
        </p>
      )}
      {job && (
        <>
          <div className={styles.row}>
            <StatusText {...JOB_STATE[job.state]} />
            <span className="muted" style={{ fontSize: 13 }}>
              run {job.id}
              {job.from_stage ? ` from ${job.from_stage}` : ""} to {job.to_stage ?? "preview"} · {log.lines.length} lines
              {log.reconnecting && " · reconnecting to the log…"}
            </span>
            <label style={{ marginLeft: "auto" }}>
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> Follow the log
            </label>
          </div>
          <pre
            ref={pre}
            className={styles.log}
            role="log"
            aria-live="off"
            aria-label="Pipeline log"
            tabIndex={0}
            onWheel={(e) => e.deltaY < 0 && setFollow(false)}
          >
            {log.lines.map((l) => l.text).join("\n") || (job.state === "queued" ? "Queued: another run is in progress…" : "")}
          </pre>
          {log.ended && (
            <p className={`${styles.end} ${styles[JOB_STATE[job.state].tone]}`} role="status">
              {JOB_STATE[job.state].glyph} {runEndText(job.state, job.exit_code, job.outcome)}
            </p>
          )}
        </>
      )}
    </section>
  );
}

