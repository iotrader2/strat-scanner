import type { ScanRow, Setup, Tf } from "./api";
import { NO_SETUP_LABEL } from "./watchlist";

/** Setups filter of the Stock Scanner (the dropdown labeled "Setups"). Leaders and the daily Ariel views use the Min RS slider; Recent breakouts, Failed breakouts, Broken leaders and the daily / weekly MACD trend changes ignore it. */
export type LeadershipFilter =
  | "leaders"
  | "laggards"
  | SetupFilter
  | "daily_bullish"
  | "daily_bearish"
  | "weekly_bullish"
  | "weekly_bearish"
  | "breakouts"
  | "failed_breakouts"
  | "broken"
  | "all";

/** One Setups option per daily setup (backend ``ariel_setups``), each listing leaders with that setup. */
export type SetupFilter =
  | "setup_ep"
  | "setup_hvc"
  | "setup_flat_base"
  | "setup_undercut"
  | "setup_ma_undercut"
  | "setup_htf"
  | "short_ep"
  | "short_hvc"
  | "short_flat_base"
  | "short_overcut"
  | "short_ma_overcut"
  | "short_ltf"
  | "setup_crossback"
  | "short_crossback"
  | "setup_wedge_pop"
  | "short_wedge_drop";

/** Setups option → the backend setup kind it lists. */
export const SETUP_FILTER_KIND: Record<SetupFilter, string> = {
  setup_ep: "episodic-pivot",
  setup_hvc: "delayed-hvc",
  setup_flat_base: "flat-base-breakout",
  setup_undercut: "undercut-rally",
  setup_ma_undercut: "ma-undercut-rally",
  setup_htf: "high-tight-flag",
  short_ep: "gap-down-pivot",
  short_hvc: "delayed-hvc-short",
  short_flat_base: "flat-base-breakdown",
  short_overcut: "overcut-fail",
  short_ma_overcut: "ma-overcut-fail",
  short_ltf: "low-tight-flag",
  setup_crossback: "ema-crossback",
  short_crossback: "ema-crossback-short",
  setup_wedge_pop: "wedge-pop",
  short_wedge_drop: "wedge-drop",
};

/**
 * Wedge Pop / Wedge Drop come right after a decline (rally), when the trend is usually still broken (intact): they
 * list RS at or above P50 (Wedge Drop: at or below) whatever the trend and the Min RS slider, like Recent breakouts.
 */
export const WEDGE_FILTERS: readonly LeadershipFilter[] = ["setup_wedge_pop", "short_wedge_drop"];

/** The short-side setup views (they list laggards instead of leaders). */
export const isShortSetupFilter = (f: string): boolean => f.startsWith("short_") && f in SETUP_FILTER_KIND;

export const isSetupFilter = (f: string): f is SetupFilter => f in SETUP_FILTER_KIND;

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
  /** Every daily setup on the row (list rows carry them without the detail text). */
  setups?: Pick<Setup, "kind" | "label" | "trigger" | "triggered" | "live" | "side">[];
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
/** The setup of ``kind`` on this row, if it has one. */
export const findSetup = (r: LeaderFields, kind: string) => r.setups?.find((s) => s.kind === kind);
/** Per-setup views: marked leaders with that daily setup, pending or triggered. They do not apply the score > 70 cut. */
const isSetupLeader = (r: LeaderFields, minRs: number, kind: string) => isLeaderAtRs(r, minRs) && !!findSetup(r, kind);
/**
 * Laggard, the mirror of a leader: RS at or below the bottom cut (1 - Min RS: P10 at the default P90 slider, P50 at
 * the slider's widest) with a broken trend (below the 50-day average or 25%+ under the 6-month high).
 */
export const isLaggardAtRs = (r: LeaderFields, minRs: number = LEADER_RS): boolean =>
  r.rs !== null && r.rs !== undefined && r.rs <= 1 - minRs + 1e-9 && isBroken(r);
/** Short setup views: laggards with that short setup, pending or triggered. */
const isSetupLaggard = (r: LeaderFields, minRs: number, kind: string) => isLaggardAtRs(r, minRs) && !!findSetup(r, kind);

/** True when the Min RS slider applies to this Setups option (Leaders, Laggards and the per-setup views). */
export function leadershipUsesMinRs(filter: LeadershipFilter): boolean {
  return filter === "leaders" || filter === "laggards" || (isSetupFilter(filter) && !WEDGE_FILTERS.includes(filter));
}

/**
 * Under a per-setup view, show that setup in the row's setup / trigger / triggered columns instead of the row's
 * top-ranked setup (a name can have several). Other views return the row unchanged.
 */
export function focusSetup<R extends ScanRow>(r: R, filter: LeadershipFilter): R {
  if (!isSetupFilter(filter)) return r;
  const s = findSetup(r, SETUP_FILTER_KIND[filter]);
  if (!s) return r;
  // Distance the price must move to the trigger: up for a long, down for a short (negative once through).
  const move = r.price > 0 ? ((s.trigger - r.price) / r.price) * 100 : null;
  const dist = move === null ? r.trigger_distance_pct : s.side === "short" ? -move : move;
  return {
    ...r,
    setup: `Daily ${s.label}`,
    trigger: Math.round(s.trigger * 100) / 100,
    triggered: s.triggered,
    triggered_live: s.live ?? false,
    setup_side: s.side ?? "long",
    trigger_distance_pct: dist,
  };
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
 * trends are never listed as leaders. The daily Ariel views are Leaders that also have a long-side daily Ariel setup
 * on the last completed daily bar (`has_setup`, from the backend's `ariel_setups`), split into awaiting trigger
 * vs already triggered. Triggered includes a break by today's session (`triggered_live`); the trigger level is
 * always the last completed day's. Daily bullish / bearish trend change is the daily MACD (6,20,9) histogram trigger on the most
 * recent daily bar with the close above (bullish) or below (bearish) the 50-day SMA (`daily_trend`, gated in the
 * backend; the raw trigger the chart arrow shows is `daily_macd_trigger`); it ignores the slider and the daily setup. Weekly
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
    case "setup_ep":
    case "setup_hvc":
    case "setup_flat_base":
    case "setup_undercut":
    case "setup_ma_undercut":
    case "setup_htf":
      return isSetupLeader(r, minRs, SETUP_FILTER_KIND[filter]);
    case "short_ep":
    case "short_hvc":
    case "short_flat_base":
    case "short_overcut":
    case "short_ma_overcut":
    case "short_ltf":
    case "short_crossback":
      return isSetupLaggard(r, minRs, SETUP_FILTER_KIND[filter]);
    case "setup_crossback":
      return isSetupLeader(r, minRs, SETUP_FILTER_KIND[filter]);
    case "setup_wedge_pop":
      return rsAtLeast(r, BREAKOUT_MIN_RS) && !!findSetup(r, SETUP_FILTER_KIND[filter]);
    case "short_wedge_drop":
      return r.rs !== null && r.rs !== undefined && r.rs <= BREAKOUT_MIN_RS && !!findSetup(r, SETUP_FILTER_KIND[filter]);
    case "laggards":
      return isLaggardAtRs(r, minRs);
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
    case "setups_pending":
    case "setups_triggered":
      // Old combined setup views (replaced by one option per setup) → Leaders.
      return { filter: "leaders", minRs: null };
    case "leaders":
    case "setup_ep":
    case "setup_hvc":
    case "setup_flat_base":
    case "setup_undercut":
    case "setup_ma_undercut":
    case "setup_htf":
    case "laggards":
    case "short_ep":
    case "short_hvc":
    case "short_flat_base":
    case "short_overcut":
    case "short_ma_overcut":
    case "short_ltf":
    case "setup_crossback":
    case "short_crossback":
    case "setup_wedge_pop":
    case "short_wedge_drop":
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

export const NO_SETUP_LEADER = "Leader · no setup";

/** Label for the setup cell of a row without a daily setup: a leader is still listed, it just has no daily setup. */
export function noSetupLabel(r: LeaderFields, minRs: number = LEADER_RS): string {
  return qualifiesAsLeader(r, minRs) ? NO_SETUP_LEADER : NO_SETUP_LABEL;
}

/** A score line's weight as shown in the breakdown, e.g. 32 -> "32%", 35.6 -> "35.6%". */
export const formatWeight = (pct: number): string => `${Number(pct.toFixed(1))}%`;
