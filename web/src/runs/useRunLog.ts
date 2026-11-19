// Follows one run's server-sent events. Lines are buffered and flushed ten times a second, so a chatty run does not
// re-render the page per line. EventSource reconnects by itself and resends Last-Event-ID; the reducer drops repeats.
import { useCallback, useEffect, useReducer, useRef } from "react";
import { urls } from "@/api/client";
import type { JobSummary } from "@/api/types";
import { emptyLog, runLogReducer, type LogLine } from "./log";

const FLUSH_MS = 100;

export function useRunLog(onEnd: (job: JobSummary) => void) {
  const [log, dispatch] = useReducer(runLogReducer, emptyLog);
  const onEndRef = useRef(onEnd);
  useEffect(() => {
    onEndRef.current = onEnd;
  });

  const attach = useCallback((job: JobSummary) => dispatch({ type: "attach", job }), []);
  const active = log.jobId !== null && !log.ended;

  useEffect(() => {
    const url = log.jobId && active ? urls.jobEvents(log.jobId) : null;
    if (!url) return;
    const source = new EventSource(url);
    let buffer: LogLine[] = [];
    const flush = () => {
      if (buffer.length) dispatch({ type: "lines", lines: buffer });
      buffer = [];
    };
    const timer = window.setInterval(flush, FLUSH_MS);
    source.addEventListener("line", (e) => buffer.push(JSON.parse((e as MessageEvent).data) as LogLine));
    source.addEventListener("state", (e) => dispatch({ type: "state", job: JSON.parse((e as MessageEvent).data) as JobSummary }));
    source.addEventListener("end", (e) => {
      const job = JSON.parse((e as MessageEvent).data) as JobSummary;
      source.close();
      flush();
      dispatch({ type: "end", job });
      onEndRef.current(job);
    });
    source.onerror = () => dispatch({ type: "reconnecting" });
    return () => {
      source.close();
      window.clearInterval(timer);
      flush();
    };
    // `active` turns false on "end"; the stream is opened once per job
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [log.jobId]);

  return { log, attach, clear: () => dispatch({ type: "clear" }) };
}
