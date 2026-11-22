// App state in two zustand stores. `useReview` holds what the UI renders from and changes rarely.
// `usePlayhead` holds the current frame and changes every animation frame: nothing subscribes to it as a React hook;
// the render loop reads it with getState() and DOM readouts follow it with `usePlayheadEffect` (no re-renders).
import type { AnimationClip } from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import { create } from "zustand";
import type { AuditReport, AuditSample, BlenderPoint, MetricTrack } from "@/audit/schema";
import { buildTracks } from "@/audit/tracks";
import type { DirectionName } from "@/motion/coords";
import { clipMatchingAudit, secondsToFrame, stepFrame } from "@/motion/time";

export type Speed = 1 | 0.5 | 0.25;

export type LoadedModel = { fileName: string; gltf: GLTF; clips: AnimationClip[] };

export type LoadedAudit = {
  fileName: string;
  report: AuditReport;
  samples: AuditSample[] | null;
  tracks: MetricTrack[];
};

type ReviewState = {
  title: string | null;
  model: LoadedModel | null;
  audit: LoadedAudit | null;
  problems: string[];
  loading: boolean;
  actionName: string | null;
  playing: boolean;
  speed: Speed;
  showProp: boolean;
  showSkeleton: boolean;
  selectedMetric: string | null;
  /** Camera request: a preset direction, framing the whole character or, with `focus`, close on an audit point. */
  view: { direction: DirectionName; focus: BlenderPoint | null; request: number };
};

const initialReview: ReviewState = {
  title: null,
  model: null,
  audit: null,
  problems: [],
  loading: false,
  actionName: null,
  playing: false,
  speed: 1,
  showProp: true,
  showSkeleton: false,
  selectedMetric: null,
  view: { direction: "s", focus: null, request: 0 },
};

export const useReview = create<ReviewState>(() => initialReview);

/** Back to nothing loaded: the review page loads its own manifest and must not show the previous page's motion. */
export function resetReview(): void {
  useReview.setState({ ...initialReview, view: { ...initialReview.view, request: useReview.getState().view.request + 1 } });
  seek(0);
}

export const usePlayhead = create<{ frame: number }>(() => ({ frame: 0 }));

export function seek(frame: number): void {
  usePlayhead.setState({ frame });
}

export type LoadResult = {
  title?: string;
  action?: string;
  model?: LoadedModel;
  report?: { fileName: string; report: AuditReport };
  samples?: AuditSample[];
  problems: string[];
};

/** Merges a load into the state: a new GLB keeps the loaded audit and the other way round. */
export function applyLoad(result: LoadResult): void {
  const state = useReview.getState();
  const problems = [...result.problems];
  const model = result.model ?? state.model;
  let audit = state.audit;
  if (result.report) {
    const samples = result.samples ?? null;
    audit = { ...result.report, samples, tracks: buildTracks(result.report.report, samples) };
  } else if (result.samples && audit) {
    audit = { ...audit, samples: result.samples, tracks: buildTracks(audit.report, result.samples) };
  } else if (result.samples) {
    problems.push("audit_samples.json needs its audit.json: drop both together.");
  }
  const actionName = pickAction(model, audit, result.action ?? (result.model ? null : state.actionName));
  useReview.setState({
    title: result.title ?? (result.model ? result.model.fileName : state.title),
    model,
    audit,
    actionName,
    problems,
    loading: false,
    selectedMetric: result.report ? null : state.selectedMetric,
    playing: false,
  });
  seek(0);
}

/** The clip the audit was run on, judged by length; null without samples or without a clip of that length. */
export function auditedAction(state: Pick<ReviewState, "model" | "audit">): string | null {
  const lastSample = state.audit?.samples?.at(-1)?.t;
  if (!state.model || lastSample === undefined) return null;
  return clipMatchingAudit(state.model.clips, lastSample);
}

/** False only when another clip is known to be the audited one: then audit points do not belong to this motion. */
export function isAuditedAction(state: Pick<ReviewState, "model" | "audit" | "actionName">): boolean {
  const audited = auditedAction(state);
  return audited === null || audited === state.actionName;
}

/** Explicit choice first, then the clip whose length matches the audit's samples, then the first clip. */
function pickAction(model: LoadedModel | null, audit: LoadedAudit | null, wanted: string | null): string | null {
  if (!model || model.clips.length === 0) return null;
  if (wanted && model.clips.some((c) => c.name === wanted)) return wanted;
  return auditedAction({ model, audit }) ?? model.clips[0]?.name ?? null;
}

export function selectAction(actionName: string): void {
  useReview.setState({ actionName });
  seek(0);
}

/** Length of the selected clip in Blender frames (0 when nothing is loaded). */
export function currentEndFrame(state: Pick<ReviewState, "model" | "actionName">): number {
  const clip = state.model?.clips.find((c) => c.name === state.actionName);
  return clip ? secondsToFrame(clip.duration) : 0;
}

/** Turns the camera to a preset direction, keeping the close-up on an audit point if there is one. */
export function requestView(direction: DirectionName): void {
  useReview.setState((s) => ({ view: { ...s.view, direction, request: s.view.request + 1 } }));
}

export function frameWholeBody(): void {
  useReview.setState((s) => ({ view: { ...s.view, focus: null, request: s.view.request + 1 } }));
}

/** Pauses and moves the playhead by `amount` frames on the quarter-frame grid. */
export function stepBy(amount: number): void {
  useReview.setState({ playing: false });
  seek(stepFrame(usePlayhead.getState().frame, amount, currentEndFrame(useReview.getState())));
}

export function togglePlaying(): void {
  useReview.setState((s) => ({ playing: !s.playing }));
}

/** Selects a metric for the 3D marker and moves the playhead to `frame`; the camera closes in on the audit's
 *  worst point when the metric has one. */
export function focusMetric(key: string, frame: number | null): void {
  const where = useReview.getState().audit?.report.errors[key]?.where ?? null;
  useReview.setState((s) => ({
    selectedMetric: key,
    playing: false,
    view: where ? { ...s.view, focus: where, request: s.view.request + 1 } : s.view,
  }));
  if (frame !== null) seek(frame);
}
