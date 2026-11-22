// Names, groups, units and order of the audit metrics: catalog.json, generated from METRICS and LABELS in
// pipeline/lib/audit_metrics.py (`python pipeline/lib/audit_metrics.py --catalog web/src/audit/catalog.json`;
// tests/test_audit_metrics.py fails when it is out of date). Keys outside it (region keys) fall back to rules below.
import catalog from "./catalog.json";
import type { MetricGroup, MetricUnit } from "./schema";

export const GROUPS: MetricGroup[] = ["penetration", "joints", "smoothness", "grip", "feet", "other"];

type CatalogEntry = { key: string; label: string; unit: MetricUnit; group: MetricGroup };
export const CATALOG: readonly CatalogEntry[] = catalog as CatalogEntry[];

const BY_KEY = new Map(CATALOG.map((m) => [m.key, m]));
const ORDER = new Map(CATALOG.map((m, i) => [m.key, i]));

export function metricLabel(key: string): string {
  return BY_KEY.get(key)?.label ?? key;
}

/** Region keys the audit measures but has no limit for (`hands_in_legs`) are still penetration. */
export function metricGroup(key: string): MetricGroup {
  return BY_KEY.get(key)?.group ?? (key.includes("_in_") ? "penetration" : "other");
}

/** The catalog's unit, as `fmt` in review_page.py; a key outside it is a distance in metres shown in cm. */
export function metricUnit(key: string): MetricUnit {
  return BY_KEY.get(key)?.unit ?? "cm";
}

export function formatValue(key: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const unit = metricUnit(key);
  if (unit === "percent") return `${(100 * value).toFixed(0)}%`;
  if (unit === "deg") return `${value.toFixed(1)}°`;
  return `${(100 * value).toFixed(1)} cm`;
}

/** The limit column: a value, "reported only" for `no_limit` metrics, "no limit" for region keys the audit does not judge. */
export function formatLimit(track: { key: string; limit: number | null; reportedOnly: boolean }): string {
  if (track.reportedOnly) return "reported only";
  return track.limit === null ? "no limit" : formatValue(track.key, track.limit);
}

export function formatShare(share: number): string {
  return `${Math.round(100 * share)}%`;
}

export function formatSide(side: string | null | undefined): string {
  if (side === "L") return "left";
  if (side === "R") return "right";
  return "";
}

/** Audit order inside each group; unknown metrics go last, alphabetically. */
export function compareMetrics(a: string, b: string): number {
  const ga = GROUPS.indexOf(metricGroup(a));
  const gb = GROUPS.indexOf(metricGroup(b));
  if (ga !== gb) return ga - gb;
  const oa = ORDER.get(a) ?? Number.MAX_SAFE_INTEGER;
  const ob = ORDER.get(b) ?? Number.MAX_SAFE_INTEGER;
  return oa !== ob ? oa - ob : a.localeCompare(b);
}
