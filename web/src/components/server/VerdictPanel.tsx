"use client";

import { useEffect, useId, useReducer, useRef, useState } from "react";
import { api } from "@/api/client";
import type { Change, Gate, TrailEntry, VerdictResult } from "@/api/types";
import { buildRequest, GATE_VERB, initialFlow, verdictFlowReducer, type Decision } from "@/review/verdictFlow";
import styles from "./server.module.css";

export function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n").filter((l) => !l.startsWith("---") && !l.startsWith("+++"));
  return (
    <pre className={styles.diff} aria-label="Change to the file, unified diff">
      {lines.map((l, i) => (
        <span key={i} className={l.startsWith("+") ? styles.added : l.startsWith("-") ? styles.removed : undefined}>
          {l.startsWith("+") ? <span className="sr-only">added: </span> : l.startsWith("-") ? <span className="sr-only">removed: </span> : null}
          {l || " "}
        </span>
      ))}
    </pre>
  );
}

function ChangeView({ change }: { change: Change }) {
  return (
    <div>
      <p style={{ margin: "0 0 4px" }}>
        <code>{change.file}</code> at <code>{change.json_path}</code>
      </p>
      <p className="muted" style={{ margin: "0 0 4px", fontSize: 13 }}>
        before: <code>{JSON.stringify(change.before)}</code>
        <br />
        after: <code>{JSON.stringify(change.after)}</code>
      </p>
      {change.diff && <DiffView diff={change.diff} />}
    </div>
  );
}

/** Approve or reject what waits at a gate. The service previews the exact write first; the reviewer confirms it. */
export function VerdictPanel({
  characterId,
  gate,
  configSha,
  onWritten,
}: {
  characterId: string;
  gate: Gate;
  configSha: string;
  onWritten: (result: VerdictResult) => void;
}) {
  const [flow, dispatch] = useReducer(verdictFlowReducer, initialFlow);
  const [note, setNote] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [posesGlb, setPosesGlb] = useState(gate.poses_options?.[0] ?? "");
  const confirmHeading = useRef<HTMLHeadingElement>(null);
  const id = useId();
  const verbs = GATE_VERB[gate.kind];

  useEffect(() => {
    if (flow.step === "confirm") confirmHeading.current?.focus();
  }, [flow.step]);

  async function preview(decision: Decision) {
    const req = buildRequest(gate.kind, gate.action, decision, note, { posesGlb, reviewer, configSha });
    if (typeof req === "string") return dispatch({ type: "fail", error: req });
    dispatch({ type: "preview", decision });
    try {
      dispatch({ type: "planned", plan: await api.previewVerdict(characterId, req) });
    } catch (e) {
      dispatch({ type: "fail", error: (e as Error).message });
    }
  }

  async function submit() {
    if (flow.step !== "confirm") return;
    const plan = flow.plan;
    dispatch({ type: "submit" });
    try {
      const result = await api.submitVerdict(characterId, { ...plan.request, expected_config_sha: plan.config_sha });
      dispatch({ type: "written", result });
      setNote("");
      onWritten(result);
    } catch (e) {
      dispatch({ type: "fail", error: (e as Error).message });
    }
  }

  if (flow.step === "confirm" || flow.step === "submitting") {
    const plan = flow.plan;
    const approve = plan.request.decision === "approve";
    return (
      <section className={styles.verdict} aria-labelledby={`${id}-confirm`}>
        <h3 id={`${id}-confirm`} ref={confirmHeading} tabIndex={-1}>
          Confirm: {plan.summary}
        </h3>
        {plan.changes.length === 0 ? (
          <p>Nothing is written except an entry in the review trail ({plan.request.note ? `note: “${plan.request.note}”` : "no note"}).</p>
        ) : (
          <>
            <p>This will be written:</p>
            {plan.changes.map((c) => (
              <ChangeView key={c.file + c.json_path} change={c} />
            ))}
          </>
        )}
        <div className={styles.row}>
          <button type="button" className={approve ? styles.primary : styles.danger} onClick={submit} disabled={flow.step === "submitting"}>
            {flow.step === "submitting" ? "Writing…" : approve ? "Write it" : "Record the rejection"}
          </button>
          <button type="button" onClick={() => dispatch({ type: "back" })} disabled={flow.step === "submitting"}>
            Back
          </button>
        </div>
      </section>
    );
  }

  const busy = flow.step === "previewing";
  return (
    <section className={styles.verdict} aria-labelledby={`${id}-title`}>
      <h3 id={`${id}-title`}>Verdict</h3>
      <p className="muted" style={{ margin: 0, fontSize: 13 }}>
        Approve writes {gate.writes ? <code>{gate.writes}</code> : "nothing but the trail"}. Reject writes nothing but the trail.
      </p>
      {gate.kind === "poses" && (gate.poses_options?.length ?? 0) > 0 && (
        <label>
          Poses GLB to approve
          <select value={posesGlb} onChange={(e) => setPosesGlb(e.target.value)}>
            {gate.poses_options!.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        Note (required to reject)
        <textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="What is right or wrong with it" />
      </label>
      <label>
        Reviewer (optional, else the service&apos;s user)
        <input type="text" value={reviewer} onChange={(e) => setReviewer(e.target.value)} autoComplete="name" />
      </label>
      {flow.step === "compose" && flow.error && (
        <p className={styles.bad} role="alert" style={{ margin: 0 }}>
          {flow.error}
        </p>
      )}
      <div className={styles.row}>
        <button type="button" className={styles.primary} onClick={() => preview("approve")} disabled={busy}>
          {verbs.approve}…
        </button>
        <button type="button" className={styles.danger} onClick={() => preview("reject")} disabled={busy}>
          {verbs.reject}…
        </button>
        {busy && (
          <span className="muted" role="status">
            Asking the service what would be written…
          </span>
        )}
      </div>
    </section>
  );
}

/** The last verdict written on this page, kept after the gate it answered goes away. */
export function VerdictWritten({ result }: { result: VerdictResult }) {
  return (
    <p className={`${styles.end} ${styles.ok}`} role="status">
      ✓ Written: {result.summary} ({new Date(result.entry.at).toLocaleString()}, {result.entry.reviewer})
    </p>
  );
}

export function VerdictHistory({ entries }: { entries: TrailEntry[] }) {
  if (entries.length === 0) return <p className="muted">No verdicts yet.</p>;
  return (
    <ol className={styles.history} reversed>
      {[...entries].reverse().map((e) => (
        <li key={e.id}>
          <strong>{e.decision === "approve" ? "✓ approved" : "✕ rejected"}</strong> {e.gate}
          {e.action ? ` · ${e.action}` : ""} · {new Date(e.at).toLocaleString()} · {e.reviewer}
          {e.note && <div>“{e.note}”</div>}
          {(e.changes ?? []).map((c) => (
            <div key={c.file + c.json_path} className="muted">
              wrote <code>{c.json_path}</code> in {c.file.split(/[\\/]/).at(-1)}
            </div>
          ))}
        </li>
      ))}
    </ol>
  );
}
