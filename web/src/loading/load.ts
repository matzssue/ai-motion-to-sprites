// Turns dropped files or a `?data=` URL into a LoadResult for the store. Everything is parsed in the browser.
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { z } from "zod";
import { AuditFileError, detectKind, parseReport, parseSamples, readJson } from "@/audit/parse";
import { applyLoad, useReview, type LoadResult, type LoadedModel } from "@/state/store";

export async function parseGlb(fileName: string, data: ArrayBuffer): Promise<LoadedModel> {
  try {
    const gltf = await new GLTFLoader().parseAsync(data, "");
    if (gltf.animations.length === 0) throw new Error("it has no animations");
    return { fileName, gltf, clips: gltf.animations };
  } catch (e) {
    throw new AuditFileError(fileName, `cannot read this GLB: ${(e as Error).message}`);
  }
}

function addJson(result: LoadResult, fileName: string, text: string): void {
  const json = readJson(fileName, text);
  if (detectKind(json) === "samples") result.samples = parseSamples(fileName, json);
  else result.report = { fileName, report: parseReport(fileName, json) };
}

function problemText(e: unknown): string {
  return e instanceof AuditFileError ? e.message : `unexpected error: ${(e as Error).message}`;
}

/** A GLB plus audit.json (or a review folder's data.json) and optionally audit_samples.json, in any order. */
export async function loadFiles(files: File[]): Promise<LoadResult> {
  const result: LoadResult = { problems: [] };
  for (const file of files) {
    const name = file.name.toLowerCase();
    try {
      if (name.endsWith(".glb")) result.model = await parseGlb(file.name, await file.arrayBuffer());
      else if (name.endsWith(".json")) addJson(result, file.name, await file.text());
      else result.problems.push(`${file.name}: skipped (expected .glb or .json)`);
    } catch (e) {
      result.problems.push(problemText(e));
    }
  }
  return result;
}

const ManifestSchema = z.object({
  title: z.string().optional(),
  action: z.string().optional(),
  glb: z.string(),
  audit: z.string(),
  samples: z.string().optional(),
});

async function fetchOk(url: URL): Promise<Response> {
  const response = await fetch(url);
  if (!response.ok) throw new AuditFileError(url.pathname, `HTTP ${response.status} for ${url.href}`);
  return response;
}

/** `?data=` points at a manifest (.json) or a folder with manifest.json; its paths are relative to the manifest. */
export async function loadFromUrl(data: string): Promise<LoadResult> {
  const result: LoadResult = { problems: [] };
  const base = new URL(data, window.location.href);
  const manifestUrl = base.pathname.endsWith(".json") ? base : new URL("manifest.json", base.href.replace(/\/?$/, "/"));
  try {
    const parsed = ManifestSchema.safeParse(await (await fetchOk(manifestUrl)).json());
    if (!parsed.success) throw new AuditFileError(manifestUrl.pathname, "manifest needs glb and audit paths");
    const manifest = parsed.data;
    result.title = manifest.title;
    result.action = manifest.action;
    const glbUrl = new URL(manifest.glb, manifestUrl);
    result.model = await parseGlb(manifest.glb, await (await fetchOk(glbUrl)).arrayBuffer());
    addJson(result, manifest.audit, await (await fetchOk(new URL(manifest.audit, manifestUrl))).text());
    if (manifest.samples) {
      addJson(result, manifest.samples, await (await fetchOk(new URL(manifest.samples, manifestUrl))).text());
    }
  } catch (e) {
    result.problems.push(problemText(e));
  }
  return result;
}

/** Shows "Loading…", then merges the result into the review store. */
export async function loadIntoReview(task: Promise<LoadResult>): Promise<void> {
  useReview.setState({ loading: true });
  applyLoad(await task);
}
