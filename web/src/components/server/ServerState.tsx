import Link from "next/link";
import { apiBase, type ApiError } from "@/api/client";
import type { Tone } from "@/pipeline/labels";
import styles from "./server.module.css";

/** A glyph and a word for a status: never colour alone. */
export function StatusText({ glyph, text, tone }: { glyph: string; text: string; tone: Tone }) {
  return (
    <span className={`${styles.status} ${styles[tone]}`}>
      <span className={styles.glyph} aria-hidden="true">
        {glyph}
      </span>
      {text}
    </span>
  );
}

const START = "python -m server <path to character.json or a folder> --fake";

/** What to show instead of a server-backed page when the service is not configured, not running, or refuses. */
export function ServerProblem({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  if (error.kind === "unconfigured") {
    return (
      <section className={styles.notice} role="status">
        <h2>The local review service is not configured</h2>
        <p>
          This page needs the review service. Build or run the web app with <code>NEXT_PUBLIC_API_BASE</code> set to its
          address, then start the service:
        </p>
        <pre>{`NEXT_PUBLIC_API_BASE=http://127.0.0.1:8765 npm run dev\n${START}`}</pre>
        <p>
          The <Link href="/">motion viewer</Link> works without it: drop a GLB and its audit files there.
        </p>
      </section>
    );
  }
  if (error.kind === "unreachable") {
    return (
      <section className={styles.notice} role="alert">
        <h2>Start the local review service</h2>
        <p>
          Nothing answers at <code>{apiBase()}</code>. Start it from the repository root (README, “Review service”):
        </p>
        <pre>{START}</pre>
        <div className={styles.row}>
          {onRetry && (
            <button type="button" onClick={onRetry}>
              Try again
            </button>
          )}
          <span className="muted">
            Or use the <Link href="/">motion viewer</Link> with dropped files.
          </span>
        </div>
      </section>
    );
  }
  return (
    <section className={styles.error} role="alert">
      <strong>The service refused: </strong>
      {error.message}
      {onRetry && (
        <>
          {" "}
          <button type="button" onClick={onRetry}>
            Try again
          </button>
        </>
      )}
    </section>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="muted" role="status">
      Loading {what}…
    </p>
  );
}
