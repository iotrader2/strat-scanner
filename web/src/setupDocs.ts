/**
 * Setups dropdown hover text, built from data/setups.yaml (served by /api/config as `setups`), so the text always
 * matches the numbers the scanner uses. Parameter names in the rules are replaced by their values.
 */
import { SETUP_FILTER_KIND, type LeadershipFilter } from "./leadership";

export interface SetupDoc {
  kind: string;
  short_kind: string;
  name: string;
  short_name: string;
  rules: string;
  entry: string;
  stop: string;
  params: Record<string, number | number[]>;
}

function fmtValue(key: string, v: number | number[]): string {
  if (Array.isArray(v)) return v.join("/");
  if (key.endsWith("_pct")) return `${v}%`;
  if (key.endsWith("_x")) return `${v}x`;
  return String(v);
}

/** Rules text with every parameter name replaced by its value ("max_depth_pct" -> "10%"). */
export function fillParams(text: string, params: SetupDoc["params"], keepLines = false): string {
  // Longest names first so "gap_day_min_gap_pct" is not cut by "min_gap_pct".
  const keys = Object.keys(params).sort((a, b) => b.length - a.length);
  let out = keepLines ? text.trim() : text.replace(/\s+/g, " ").trim();
  for (const k of keys) out = out.split(k).join(fmtValue(k, params[k]));
  return out;
}

const LONG_LEAD =
  "Leaders (P90+ and trend not broken; the Min RS slider can raise the cut; no score cut) with this setup, pending or triggered. ";
const SHORT_LEAD =
  "Laggards (RS at or below the bottom cut, P10 by default; trend broken) with this short setup, pending or triggered. ";

/** Hover text for one Setups option, or null when the option is not a setup (or the doc is missing). */
export function setupHint(filter: LeadershipFilter, docs: SetupDoc[] | undefined): string | null {
  if (!docs || !(filter in SETUP_FILTER_KIND)) return null;
  const kind = SETUP_FILTER_KIND[filter as keyof typeof SETUP_FILTER_KIND];
  const long = docs.find((d) => d.kind === kind);
  if (long) {
    return `${LONG_LEAD}${fillParams(long.rules, long.params)} Entry: ${fillParams(long.entry, long.params)} Stop: ${fillParams(long.stop, long.params)}`;
  }
  const mirror = docs.find((d) => d.short_kind === kind);
  if (!mirror) return null;
  return `${SHORT_LEAD}The ${mirror.name} with the chart turned upside down (same numbers: a rise becomes a drop, above becomes below, a low stop becomes a high stop). Long rules: ${fillParams(mirror.rules, mirror.params)}`;
}

/** The setup's name from setups.yaml (long or short), or null when the option is not a setup. */
export function setupLabel(filter: LeadershipFilter, docs: SetupDoc[] | undefined): string | null {
  if (!docs || !(filter in SETUP_FILTER_KIND)) return null;
  const kind = SETUP_FILTER_KIND[filter as keyof typeof SETUP_FILTER_KIND];
  const long = docs.find((d) => d.kind === kind);
  if (long) return long.name;
  return docs.find((d) => d.short_kind === kind)?.short_name ?? null;
}

export interface SetupsOverview {
  how_it_works: string[];
  short_setups: string;
  general: Record<string, number | number[]>;
}

/** The Setups option (long or short) that lists ``kind``, e.g. "flat-base-breakdown" -> "short_flat_base". */
export function filterForKind(kind: string): LeadershipFilter | null {
  const hit = Object.entries(SETUP_FILTER_KIND).find(([, k]) => k === kind);
  return hit ? (hit[0] as LeadershipFilter) : null;
}

/** Rule text split into numbered steps: "1. ...\n   more\n2. ..." -> ["...more", "..."]. Plain text is one step. */
export function ruleSteps(text: string, params: SetupDoc["params"]): string[] {
  const filled = fillParams(text, params, true);
  const parts = filled.split(/\n(?=\s*\d+\.\s)/).map((p) => p.replace(/^\s*\d+\.\s*/, "").replace(/\s+/g, " ").trim());
  return parts.filter(Boolean);
}

/** "min_gap_pct" -> "Min gap". */
export function paramLabel(key: string): string {
  const words = key
    .replace(/_(pct|x)$/, "")
    .split("_")
    .map((w) => (w === "ma" ? "MA" : w))
    .join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export { fmtValue as paramValue };
