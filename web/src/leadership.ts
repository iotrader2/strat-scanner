import type { ScanRow, Tf } from "./api";
import { NO_SETUP_LABEL } from "./watchlist";

/** Setups filter of the Stock Scanner (the dropdown labeled "Setups"). Leaders and the weekly Strat views use the Min RS slider; Recent breakouts, Failed breakouts, Broken leaders and the daily / weekly MACD trend changes ignore it. */
export type LeadershipFilter =
  | "leaders"
  | "setups_pending"
  | "setups_triggered"
  | "daily_bullish"
  | "daily_bearish"
  | "weekly_bullish"
  | "weekly_bearish"
  | "breakouts"
  | "failed_breakouts"
  | "broken"
  | "all";

export const LEADER_RS = 0.9;
/** The Leaders view also needs a top score, strictly above this; matches the backend `LEADERS_MIN_SCORE`. A list filter
 * only: the leader flag / badge stays RS + trend (the score is itself built from leader status and breakdown). */
export const LEADERS_MIN_SCORE = 70;
export const MIN_RS_RANGE = { min: 50, max: 99, default: 90 };
/** Relative-strength floor for Recent breakouts (future leaders may still be mid-pack); matches the backend `MIN_RS`. */
export const BREAKOUT_MIN_RS = 0.5;

type LeaderFields = Pick<ScanRow, "rs"> & {
  score?: number;
  /** The backend's leader flag (RS >= P90 and trend not broken). Rows without it fall back to the same rule. */
  is_leader?: boolean;
  /** RS line versus QQQ made a 52-week high in the last 5 sessions. Absent on older rows. */
  rs_line_high?: boolean;
  has_setup?: boolean;
  triggered?: boolean | null;
  daily_trend?: ScanRow["daily_trend"];
  weekly_trend?: ScanRow["weekly_trend"];
  leadership?: Pick<ScanRow["leadership"], "breakdown">;
  breakout?: ScanRow["breakout"];
  failed_breakout?: ScanRow["failed_breakout"];
};

const rsAtLeast = (r: LeaderFields, min: number) => r.rs !== null && r.rs !== undefined && r.rs >= min;
const isBroken = (r: LeaderFields) => r.leadership?.breakdown === "broken";
/** Marked leader by the backend: RS at or above P90 with the trend intact (a weakening trend still counts). */
export const isLeader = (r: LeaderFields): boolean => r.is_leader ?? (rsAtLeast(r, LEADER_RS) && !isBroken(r));
/** Marked leader at the Min RS slider: the slider can raise the cut above P90 but never adds non-leaders. */
const isLeaderAtRs = (r: LeaderFields, minRs: number) => isLeader(r) && rsAtLeast(r, minRs);
/** RS line versus QQQ at a 52-week high in the last 5 sessions. An alternative to the P90 floor, not to a tighter slider. */
const rsLineHigh = (r: LeaderFields): boolean => r.rs_line_high === true;
/** Score strictly above `LEADERS_MIN_SCORE` (70). */
export const hasLeaderScore = (r: Pick<LeaderFields, "score">): boolean =>
  typeof r.score === "number" && r.score > LEADERS_MIN_SCORE;
/**
 * RS side of the Leaders list: marked leader at the slider's cut, or (while the slider is at or below P90) an
 * RS-line 52-week high. Lowering the slider still does not add other names below P90. A broken trend is out.
 */
const qualifiesAsLeader = (r: LeaderFields, minRs: number) =>
  !isBroken(r) && (isLeaderAtRs(r, minRs) || (rsLineHigh(r) && minRs <= LEADER_RS));
/** Leaders view: that RS qualification and a score above 70. */
const isListedLeader = (r: LeaderFields, minRs: number) => qualifiesAsLeader(r, minRs) && hasLeaderScore(r);
/** Weekly Strat views: marked leaders with a weekly setup. They do not apply the score > 70 cut. */
const isSetupLeader = (r: LeaderFields, minRs: number) => isLeaderAtRs(r, minRs) && !!r.has_setup;

/** True when the Min RS slider applies to this Setups option (Leaders and both weekly Strat views). */
export function leadershipUsesMinRs(filter: LeadershipFilter): boolean {
  return filter === "leaders" || filter === "setups_pending" || filter === "setups_triggered";
}

/** Chart timeframe the detail page opens on when a row is clicked under this Setups option: Daily for the daily trend
 * changes, Weekly for the weekly ones. Null leaves the page's sticky choice alone. */
export function detailTfFor(filter: LeadershipFilter): Tf | null {
  if (filter === "daily_bullish" || filter === "daily_bearish") return "D";
  if (filter === "weekly_bullish" || filter === "weekly_bearish") return "W";
  return null;
}

/** Chip shown on a scan row with a Daily bullish / bearish trend change setup (MACD trigger on the latest bar, confirmed by the 50-day SMA). */
export function dailyTrendBadge(
  trend: ScanRow["daily_trend"],
): { label: string; tone: "bull" | "bear"; title: string } | null {
  if (trend === "bullish") {
    return {
      label: "Daily bullish",
      tone: "bull",
      title: "Daily MACD (6,20,9): first green histogram bar after 3 or more red bars, on the latest daily bar, with the close above the 50-day SMA",
    };
  }
  if (trend === "bearish") {
    return {
      label: "Daily bearish",
      tone: "bear",
      title: "Daily MACD (6,20,9): first red histogram bar after 3 or more green bars, on the latest daily bar, with the close below the 50-day SMA",
    };
  }
  return null;
}

/** Chip shown on a scan row with a Weekly bullish / bearish trend change setup (MACD trigger on the current week, confirmed by the 10-week SMA). */
export function weeklyTrendBadge(
  trend: ScanRow["weekly_trend"],
): { label: string; tone: "bull" | "bear"; title: string } | null {
  if (trend === "bullish") {
    return {
      label: "Weekly bullish",
      tone: "bull",
      title: "Weekly MACD (6,20,9): first green histogram bar after 3 or more red bars, on the current weekly bar, with the latest close above the 10-week SMA",
    };
  }
  if (trend === "bearish") {
    return {
      label: "Weekly bearish",
      tone: "bear",
      title: "Weekly MACD (6,20,9): first red histogram bar after 3 or more green bars, on the current weekly bar, with the latest close below the 10-week SMA",
    };
  }
  return null;
}

/**
 * Whether a scan row passes the Stock Scanner "Setups" filter. `minRs` is the slider as a 0..1 percentile. Broken
 * trends are never listed as leaders. The weekly Strat views are Leaders that also have a long-side weekly Strat setup
 * on the last completed weekly candle (`has_setup`, from the backend's `find_long_setups`), split into awaiting trigger
 * vs already triggered. Triggered includes a break by the week in progress (`triggered_live`); the trigger level is
 * always the last completed week's. Daily bullish / bearish trend change is the daily MACD (6,20,9) histogram trigger on the most
 * recent daily bar with the close above (bullish) or below (bearish) the 50-day SMA (`daily_trend`, gated in the
 * backend; the raw trigger the chart arrow shows is `daily_macd_trigger`); it ignores the slider and the weekly setup. Weekly
 * bullish / bearish trend change is the same trigger on the current (in-progress) weekly bar, gated on the 10-week SMA
 * (`weekly_trend`); it also ignores the slider. Recent breakouts ignores the slider:
 * it needs a tight-base breakout and RS >= P50. Broken leaders ignores the slider: any name whose trend is broken
 * (same flag as the RS chip). Failed breakouts is the opposite of Recent breakouts: a breakout of the last 8 weeks
 * whose level price has since lost (`failed_breakout`, from the backend), RS >= P50, any trend; it ignores the slider.
 * A failed breakout is no longer listed under Recent breakouts.
 */
export function matchesLeadership(r: LeaderFields, filter: LeadershipFilter, minRs: number = LEADER_RS): boolean {
  switch (filter) {
    case "leaders":
      return isListedLeader(r, minRs);
    case "setups_pending":
      return isSetupLeader(r, minRs) && !r.triggered;
    case "setups_triggered":
      return isSetupLeader(r, minRs) && r.triggered === true;
    case "daily_bullish":
      return r.daily_trend === "bullish";
    case "daily_bearish":
      return r.daily_trend === "bearish";
    case "weekly_bullish":
      return r.weekly_trend === "bullish";
    case "weekly_bearish":
      return r.weekly_trend === "bearish";
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
    case "daily_bullish":
    case "daily_bearish":
    case "weekly_bullish":
    case "weekly_bearish":
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

export const NO_SETUP_LEADER = "Leader · no setup";

/** Label for the setup cell of a row without a weekly setup: a leader is still listed, it just has no weekly setup. */
export function noSetupLabel(r: LeaderFields, minRs: number = LEADER_RS): string {
  return qualifiesAsLeader(r, minRs) ? NO_SETUP_LEADER : NO_SETUP_LABEL;
}

/** A score line's weight as shown in the breakdown, e.g. 32 -> "32%", 35.6 -> "35.6%". */
export const formatWeight = (pct: number): string => `${Number(pct.toFixed(1))}%`;
