// Log of one run as the event stream delivers it. Lines carry their index, so a reconnect that resends lines does not
// duplicate them and a gap (lines dropped on the server) is visible.
import type { JobSummary } from "@/api/types";

export const MAX_SHOWN = 5000;

export type LogLine = { n: number; text: string };

export type RunLog = {
  jobId: string | null;
  lines: LogLine[];
  /** index of the next expected line */
  next: number;
  job: JobSummary | null;
  ended: boolean;
  /** the stream failed and the browser is retrying */
  reconnecting: boolean;
};

export type RunLogEvent =
  | { type: "attach"; job: JobSummary }
  | { type: "lines"; lines: LogLine[] }
  | { type: "state"; job: JobSummary }
  | { type: "end"; job: JobSummary }
  | { type: "reconnecting" }
  | { type: "clear" };

export const emptyLog: RunLog = { jobId: null, lines: [], next: 0, job: null, ended: false, reconnecting: false };

export function runLogReducer(state: RunLog, event: RunLogEvent): RunLog {
  switch (event.type) {
    case "attach":
      if (state.jobId === event.job.id) return { ...state, job: event.job };
      return { ...emptyLog, jobId: event.job.id, job: event.job, ended: !isActive(event.job) };
    case "lines": {
      const fresh = event.lines.filter((l) => l.n >= state.next).sort((a, b) => a.n - b.n);
      if (fresh.length === 0) return state.reconnecting ? { ...state, reconnecting: false } : state;
      const lines = [...state.lines, ...fresh];
      return { ...state, lines: lines.length > MAX_SHOWN ? lines.slice(-MAX_SHOWN) : lines, next: fresh.at(-1)!.n + 1, reconnecting: false };
    }
    case "state":
      return { ...state, job: event.job, reconnecting: false };
    case "end":
      return { ...state, job: event.job, ended: true, reconnecting: false };
    case "reconnecting":
      return state.ended ? state : { ...state, reconnecting: true };
    case "clear":
      return emptyLog;
  }
}

export function isActive(job: JobSummary | null | undefined): boolean {
  return job?.state === "queued" || job?.state === "running";
}
