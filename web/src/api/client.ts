// Client of the local review service (server/). The base URL is NEXT_PUBLIC_API_BASE, inlined at build time; without
// it, or when the service does not answer, calls fail with an ApiError the pages turn into a "start the server" state.
import type { operations } from "./schema";
import type {
  CharacterSummary,
  Health,
  JobSummary,
  PipelineState,
  ReviewSource,
  RunRequest,
  TrailEntry,
  VerdictPlan,
  VerdictRequest,
  VerdictResult,
} from "./types";

export type ApiErrorKind = "unconfigured" | "unreachable" | "http";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status: number | null = null,
    readonly detail: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** The configured base URL without a trailing slash, or null. */
export function apiBase(env: string | undefined = process.env.NEXT_PUBLIC_API_BASE): string | null {
  const base = env?.trim();
  return base ? base.replace(/\/+$/, "") : null;
}

/** FastAPI errors carry `detail`: a string, a validation list or an object with a message. */
export function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === "object" && d && "msg" in d ? `${(d as { loc?: unknown[] }).loc?.slice(1).join(".") ?? ""}: ${String(d.msg)}` : String(d)))
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const d = detail as { message?: unknown; problems?: unknown };
    const problems = Array.isArray(d.problems) ? ` (${d.problems.map(String).join("; ")})` : "";
    if (typeof d.message === "string") return d.message + problems;
  }
  return JSON.stringify(detail);
}

type Init = { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal };

/** fetch() against the service: JSON in and out, errors as ApiError. `fetchImpl` is for tests. */
export async function request<T>(path: string, init: Init = {}, base = apiBase(), fetchImpl: typeof fetch = fetch): Promise<T> {
  if (!base) throw new ApiError("unconfigured", "NEXT_PUBLIC_API_BASE is not set");
  let response: Response;
  try {
    response = await fetchImpl(base + path, {
      method: init.method ?? "GET",
      headers: init.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      signal: init.signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("unreachable", `cannot reach the review service at ${base}`);
  }
  const text = await response.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = text;
  }
  if (!response.ok) {
    const detail = json && typeof json === "object" && "detail" in json ? (json as { detail: unknown }).detail : json;
    throw new ApiError("http", `${response.status}: ${detailText(detail)}`, response.status, detail);
  }
  return json as T;
}

const enc = encodeURIComponent;

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/api/health", { signal }),
  characters: (signal?: AbortSignal) => request<CharacterSummary[]>("/api/characters", { signal }),
  character: (id: string, signal?: AbortSignal) => request<PipelineState>(`/api/characters/${enc(id)}`, { signal }),
  verdicts: (id: string, action?: string, signal?: AbortSignal) =>
    request<TrailEntry[]>(`/api/characters/${enc(id)}/verdicts${action ? `?action=${enc(action)}` : ""}`, { signal }),
  previewVerdict: (id: string, body: VerdictRequest) =>
    request<VerdictPlan>(`/api/characters/${enc(id)}/verdicts/preview`, { method: "POST", body }),
  submitVerdict: (id: string, body: VerdictRequest) =>
    request<VerdictResult>(`/api/characters/${enc(id)}/verdicts`, { method: "POST", body }),
  startRun: (id: string, body: RunRequest) => request<JobSummary>(`/api/characters/${enc(id)}/runs`, { method: "POST", body }),
  cancelJob: (jobId: string) => request<JobSummary>(`/api/jobs/${enc(jobId)}/cancel`, { method: "POST", body: {} }),
  job: (jobId: string) => request<JobSummary>(`/api/jobs/${enc(jobId)}`),
};

/** Absolute URLs for things the browser loads itself (viewer manifest, images, event stream); null without a base. */
export const urls = {
  manifest: (id: string, action: string, source: ReviewSource, base = apiBase()) =>
    base && `${base}/api/characters/${enc(id)}/actions/${enc(action)}/manifest.json?source=${source}`,
  /** Image ids from the service are paths under its base. */
  image: (imageId: string, base = apiBase()) => base && base + imageId,
  jobEvents: (jobId: string, base = apiBase()) => base && `${base}/api/jobs/${enc(jobId)}/events`,
};

// compile-time check that the hand-picked aliases above match the operations they call
type Json<O extends keyof operations, S extends number = 200> = operations[O]["responses"] extends Record<S, { content: { "application/json": infer T } }> ? T : never;
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
const contract: [
  Same<Json<"get_character">, PipelineState>,
  Same<Json<"list_characters">, CharacterSummary[]>,
  Same<Json<"submit_verdict">, VerdictResult>,
  Same<Json<"start_run", 202>, JobSummary>,
] = [true, true, true, true];
void contract;
