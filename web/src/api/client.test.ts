import { describe, expect, it, vi } from "vitest";
import { ApiError, apiBase, detailText, request, urls } from "./client";
import { initialResource, resourceReducer, toApiError } from "./resource";

const base = "http://127.0.0.1:8765";

function respond(status: number, body: unknown) {
  return vi.fn(async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status }));
}

describe("apiBase", () => {
  it("is null when unset or blank and loses trailing slashes", () => {
    expect(apiBase(undefined)).toBeNull();
    expect(apiBase("  ")).toBeNull();
    expect(apiBase("http://127.0.0.1:8765//")).toBe(base);
  });
});

describe("request", () => {
  it("fails as unconfigured without a base URL, without calling fetch", async () => {
    const f = vi.fn();
    await expect(request("/api/characters", {}, null, f)).rejects.toMatchObject({ kind: "unconfigured" });
    expect(f).not.toHaveBeenCalled();
  });

  it("turns a network error into unreachable", async () => {
    const f = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const e = (await request("/api/characters", {}, base, f).catch((x: unknown) => x)) as ApiError;
    expect(e).toBeInstanceOf(ApiError);
    expect(e.kind).toBe("unreachable");
    expect(e.message).toContain(base);
  });

  it("lets an abort through as an abort", async () => {
    const f = vi.fn(async () => {
      throw new DOMException("aborted", "AbortError");
    });
    await expect(request("/x", {}, base, f)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("sends JSON with its content type and parses the answer", async () => {
    const f = respond(200, { ok: 1 });
    expect(await request("/api/x", { method: "POST", body: { a: 1 } }, base, f)).toEqual({ ok: 1 });
    expect(f).toHaveBeenCalledWith(`${base}/api/x`, expect.objectContaining({ method: "POST", body: '{"a":1}', headers: { "Content-Type": "application/json" } }));
  });

  it("reports the service's detail on an HTTP error", async () => {
    const e = (await request("/x", {}, base, respond(409, { detail: "a run is active" })).catch((x: unknown) => x)) as ApiError;
    expect(e).toMatchObject({ kind: "http", status: 409, detail: "a run is active" });
    expect(e.message).toBe("409: a run is active");
  });
});

describe("detailText", () => {
  it("reads strings, validation lists and schema refusals", () => {
    expect(detailText("plain")).toBe("plain");
    expect(detailText([{ loc: ["body", "decision"], msg: "Input should be 'approve' or 'reject'" }])).toBe(
      "decision: Input should be 'approve' or 'reject'",
    );
    expect(detailText({ message: "would not match", problems: ["$.a: bad"] })).toBe("would not match ($.a: bad)");
  });
});

describe("urls", () => {
  it("builds absolute URLs and encodes names", () => {
    expect(urls.manifest("wy buch", "attack", "choice", base)).toBe(
      `${base}/api/characters/wy%20buch/actions/attack/manifest.json?source=choice`,
    );
    expect(urls.image("/api/characters/a/images/rig/0", base)).toBe(`${base}/api/characters/a/images/rig/0`);
    expect(urls.jobEvents("j1", null)).toBeNull();
  });
});

describe("resourceReducer", () => {
  it("keeps data on screen while reloading and after a failed reload", () => {
    let s = resourceReducer(initialResource<number>(), { type: "start" });
    expect(s).toMatchObject({ loading: true, refreshing: false });
    s = resourceReducer(s, { type: "ok", data: 1 });
    s = resourceReducer(s, { type: "start" });
    expect(s).toMatchObject({ data: 1, loading: false, refreshing: true });
    s = resourceReducer(s, { type: "fail", error: new ApiError("unreachable", "down") });
    expect(s).toMatchObject({ data: 1, loading: false, refreshing: false });
    expect(s.error?.kind).toBe("unreachable");
  });

  it("wraps unknown errors", () => {
    expect(toApiError(new Error("boom"))).toMatchObject({ kind: "http", message: "boom" });
  });
});
