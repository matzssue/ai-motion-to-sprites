// Loading state of one server resource. A reload keeps the last data on screen (with `refreshing`) instead of
// flashing a spinner; an error after data keeps the data and shows the error next to it.
import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError } from "./client";

export type Resource<T> = {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** a reload while data is shown */
  refreshing: boolean;
};

export type ResourceEvent<T> = { type: "start" } | { type: "ok"; data: T } | { type: "fail"; error: ApiError };

export function initialResource<T>(): Resource<T> {
  return { data: null, error: null, loading: true, refreshing: false };
}

export function resourceReducer<T>(state: Resource<T>, event: ResourceEvent<T>): Resource<T> {
  switch (event.type) {
    case "start":
      return { ...state, loading: state.data === null, refreshing: state.data !== null };
    case "ok":
      return { data: event.data, error: null, loading: false, refreshing: false };
    case "fail":
      return { ...state, error: event.error, loading: false, refreshing: false };
  }
}

export function toApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError("http", (e as Error)?.message ?? String(e));
}

/** Loads on mount and whenever `key` changes; `reload()` loads again. Late answers of an older load are dropped. */
export function useResource<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): [Resource<T>, () => void] {
  const [state, dispatch] = useReducer(resourceReducer<T>, undefined, initialResource<T>);
  const loadRef = useRef(load);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    loadRef.current = load;
  });

  const run = useCallback(() => {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    dispatch({ type: "start" });
    loadRef.current(c.signal).then(
      (data) => !c.signal.aborted && dispatch({ type: "ok", data }),
      (e) => !c.signal.aborted && dispatch({ type: "fail", error: toApiError(e) }),
    );
  }, []);

  useEffect(() => {
    if (key === null) return;
    run();
    return () => controller.current?.abort();
  }, [key, run]);

  return [state, run];
}
