import type { ScanRow } from "./api";
import { NO_SETUP_LABEL } from "./watchlist";

/** Leadership filter of the Stock Scanner. Leaders and Weekly setups use the Min RS slider; Recent breakouts, Failed breakouts and Broken leaders ignore it. */
export type LeadershipFilter =
  | "leaders"
  | "setups_pending"
  | "setups_triggered"
  | "breakouts"
  | "failed_breakouts"
  | "broken"
  | "all";

export const LEADER_RS = 0.9;
export const MIN_RS_RANGE = { min: 50, max: 99, default: 90 };
/** Relative-strength floor for Recent breakouts (future leaders may still be mid-pack); matches the backend `MIN_RS`. */
export const BREAKOUT_MIN_RS = 0.5;

type LeaderFields = Pick<ScanRow, "rs"> & {
  has_setup?: boolean;
  triggered?: boolean | null;
  leadership?: Pick<ScanRow["leadership"], "breakdown">;
  breakout?: ScanRow["breakout"];
  failed_breakout?: ScanRow["failed_breakout"];
};

const rsAtLeast = (r: LeaderFields, min: number) => r.rs !== null && r.rs !== undefined && r.rs >= min;
const isBroken = (r: LeaderFields) => r.leadership?.breakdown === "broken";
const isSetupLeader = (r: LeaderFields, minRs: number) => rsAtLeast(r, minRs) && !isBroken(r) && !!r.has_setup;

/** True when the Min RS slider applies to this Leadership option (Leaders and both Weekly setups views). */
export function leadershipUsesMinRs(filter: LeadershipFilter): boolean {
  return filter === "leaders" || filter === "setups_pending" || filter === "setups_triggered";
}

/**
 * Whether a scan row passes the Stock Scanner "Leadership" filter. `minRs` is the slider as a 0..1 percentile. Broken
 * trends are never listed as leaders. Weekly setups is Leaders that also have a long-side weekly Strat setup on the latest
 * weekly candle (`has_setup`, from the backend's `find_long_setups`), split into awaiting trigger vs already triggered.
 * Recent breakouts ignores the slider: it needs a tight-base breakout and RS >= P50. Broken leaders ignores the slider:
 * any name whose trend is broken (same flag as the RS chip). Failed breakouts is the opposite of Recent breakouts: a
 * breakout of the last 8 weeks whose level price has since lost (`failed_breakout`, from the backend), RS >= P50, any
 * trend; it ignores the slider. A failed breakout is no longer listed under Recent breakouts.
 */
export function matchesLeadership(r: LeaderFields, filter: LeadershipFilter, minRs: number = LEADER_RS): boolean {
  switch (filter) {
    case "leaders":
      return rsAtLeast(r, minRs) && !isBroken(r);
    case "setups_pending":
      return isSetupLeader(r, minRs) && !r.triggered;
    case "setups_triggered":
      return isSetupLeader(r, minRs) && r.triggered === true;
    case "broken":
      return isBroken(r);
    case "breakouts":
      return !!r.breakout && !r.failed_breakout && rsAtLeast(r, BREAKOUT_MIN_RS) && !isBroken(r);
    case "failed_breakouts":
      return !!r.failed_breakout && rsAtLeast(r, BREAKOUT_MIN_RS);
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
    case "setups":
      // Old combined Weekly setups option → the actionable awaiting-trigger view.
      return { filter: "setups_pending", minRs: null };
    case "leaders":
    case "setups_pending":
    case "setups_triggered":
    case "breakouts":
    case "failed_breakouts":
    case "broken":
    case "all":
      return { filter: saved, minRs: null };
    default:
      return { filter: "leaders", minRs: null };
  }
}

/** "Failed breakout 2026-09-14 · 6.2% below" text for the badge (the level is in the tooltip and the Level column). */
export function failedBreakoutLabel(f: NonNullable<ScanRow["failed_breakout"]>): string {
  return `Failed breakout ${f.week} · ${Math.abs(f.below_pct).toFixed(1)}% below`;
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
