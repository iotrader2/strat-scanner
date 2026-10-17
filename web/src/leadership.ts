import type { ScanRow } from "./api";
import { NO_SETUP_LABEL } from "./watchlist";

/** Leadership filter of the Stock Scanner. Leaders and Broken leaders use the Min RS slider; Recent breakouts has its own floor. */
export type LeadershipFilter = "leaders" | "breakouts" | "broken" | "all";

export const LEADER_RS = 0.9;
export const MIN_RS_RANGE = { min: 50, max: 99, default: 90 };
/** Relative-strength floor for Recent breakouts (future leaders may still be mid-pack); matches the backend `MIN_RS`. */
export const BREAKOUT_MIN_RS = 0.5;

type LeaderFields = Pick<ScanRow, "rs"> & {
  leadership?: Pick<ScanRow["leadership"], "breakdown">;
  breakout?: ScanRow["breakout"];
};

const rsAtLeast = (r: LeaderFields, min: number) => r.rs !== null && r.rs !== undefined && r.rs >= min;
const isBroken = (r: LeaderFields) => r.leadership?.breakdown === "broken";

/**
 * Whether a scan row passes the Stock Scanner "Leadership" filter. `minRs` is the slider as a 0..1 percentile. Broken
 * trends are never listed as leaders. Recent breakouts ignores the slider: it needs a tight-base breakout and RS >= P50.
 */
export function matchesLeadership(r: LeaderFields, filter: LeadershipFilter, minRs: number = LEADER_RS): boolean {
  switch (filter) {
    case "leaders":
      return rsAtLeast(r, minRs) && !isBroken(r);
    case "broken":
      return rsAtLeast(r, minRs) && isBroken(r);
    case "breakouts":
      return !!r.breakout && rsAtLeast(r, BREAKOUT_MIN_RS) && !isBroken(r);
    default:
      return true;
  }
}

/** The slider (50-99) as a 0..1 percentile. */
export const sliderToRs = (v: number): number => v / 100;

/** Saved filters from before "Leaders" and "Broad leaders" were merged: P80 becomes Leaders at Min RS 80. */
export function migrateLeadership(saved: string | null | undefined): { filter: LeadershipFilter; minRs: number | null } {
  switch (saved) {
    case "p90":
      return { filter: "leaders", minRs: 90 };
    case "p80":
      return { filter: "leaders", minRs: 80 };
    case "leaders":
    case "breakouts":
    case "broken":
    case "all":
      return { filter: saved, minRs: null };
    default:
      return { filter: "leaders", minRs: null };
  }
}

/** "Breakout 2026-09-14 · 6-week base" text for the badge. */
export function breakoutLabel(b: NonNullable<ScanRow["breakout"]>): string {
  return `Breakout ${b.week} · ${b.base_weeks}-week base`;
}

/** "P97" style label for a 0..1 relative-strength percentile. */
export function fmtRs(rs: number | null | undefined): string {
  return rs === null || rs === undefined ? "—" : `P${Math.round(rs * 100)}`;
}

export interface TriggerHint {
  price: number;
  distancePct: number;
  label: string;
}

/** The trigger to show for a row: its weekly setup's, or for a name with no setup the nearest weekly high above price. */
export function triggerHint(
  r: Pick<ScanRow, "trigger" | "trigger_distance_pct" | "nearest_trigger" | "nearest_trigger_distance_pct" | "nearest_trigger_label">,
): (TriggerHint & { nearest: boolean }) | null {
  if (r.trigger !== null && r.trigger !== undefined) {
    return { price: r.trigger, distancePct: r.trigger_distance_pct ?? 0, label: "setup trigger", nearest: false };
  }
  if (r.nearest_trigger !== null && r.nearest_trigger !== undefined) {
    return {
      price: r.nearest_trigger,
      distancePct: r.nearest_trigger_distance_pct ?? 0,
      label: r.nearest_trigger_label ?? "nearest weekly high",
      nearest: true,
    };
  }
  return null;
}

export const NO_SETUP_LEADER = "No setup / leader";

/** Label for the setup cell of a row without a weekly setup. */
export function noSetupLabel(r: LeaderFields, minRs: number = LEADER_RS): string {
  return rsAtLeast(r, minRs) && !isBroken(r) ? NO_SETUP_LEADER : NO_SETUP_LABEL;
}

/** A score line's weight as shown in the breakdown, e.g. 32 -> "32%", 35.6 -> "35.6%". */
export const formatWeight = (pct: number): string => `${Number(pct.toFixed(1))}%`;
