/** Morning Leaders view helpers. The numbers come from the API; this only formats and orders them. */

export const CHECK_INS = ["09:45", "10:00", "10:15", "10:30", "10:45"] as const;
export type CheckIn = (typeof CHECK_INS)[number];
export type MorningMode = "leaders" | CheckIn;

export interface WindowOutcome {
  rank?: number | null;
  qualified?: number | null;
  cross_time?: string | null;
  score?: number;
  day_move?: number | null;
  vs_qqq?: number | null;
  or_position?: number | null;
  eod_ret?: number | null;
  d1_ret?: number | null;
  d2_ret?: number | null;
  d3_ret?: number | null;
  d4_ret?: number | null;
  d5_ret?: number | null;
  stopped?: number | null;
  stop_day?: number | null;
  stop_ret?: number | null;
  gapped?: number | null;
  mfe?: number | null;
  mae?: number | null;
}

export interface MorningRow {
  rank: number;
  symbol: string;
  name: string;
  score: number;
  rs: number | null;
  as_of: string;
  windows: Record<string, WindowOutcome>;
}

export interface MorningDay {
  date: string;
  weekday: string;
  month_day: string;
  closed: boolean;
  rows: MorningRow[];
}

export interface HorizonStat {
  n_days: number;
  n_trades: number;
  avg: number | null;
  median: number | null;
  win_rate: number | null;
  expectancy: number | null;
  stop_hit_rate: number | null;
  total_r?: number | null;
  gap_count?: number | null;
  avg_mfe?: number | null;
}

export interface WindowStat {
  n_days: number;
  n_trades: number;
  horizons: Record<string, HorizonStat>;
  vs_qqq: Record<string, number | null>;
  avg_qualified?: number | null;
  qualified_days?: number;
}

export interface BestWindow {
  window: string;
  horizon: string;
  expectancy: number;
  win_rate: number | null;
  avg: number | null;
  median: number | null;
  stop_hit_rate: number | null;
  n_days: number;
  n_trades: number;
  total_r?: number | null;
  avg_mfe?: number | null;
  gap_count?: number | null;
  vs_qqq: number | null;
  avg_qualified?: number | null;
}

export interface MorningStats {
  windows: Record<string, WindowStat>;
  qqq: Record<string, { n_days: number; n_trades: number; horizons: Record<string, HorizonStat> }>;
  best: BestWindow | null;
  primary_horizon: string;
  definition: string;
}

export interface MorningWeek {
  week_of: string;
  title: string;
  this_week: boolean;
  prev: string | null;
  next: string | null;
  windows: string[];
  days: MorningDay[];
  stats: MorningStats;
}

export function displayTime(window: string): string {
  const [hour, minute] = window.split(":");
  return `${Number(hour)}:${minute}`;
}

export function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const text = Math.abs(value).toFixed(digits);
  if (Number(text) === 0) return `${(0).toFixed(digits)}%`;
  return `${value > 0 ? "+" : "-"}${text}%`;
}

/** 1R is 1% of the entry, so the stored percent is already in R. */
export function signedR(value: number | null | undefined, digits = 1): string {
  const text = signedPct(value, digits);
  return text === "—" ? text : text.replace("%", "R");
}

const HORIZON_AT = { eod_ret: 0, d1_ret: 1, d2_ret: 2, d3_ret: 3, d4_ret: 4, d5_ret: 5 } as const;
type HorizonField = keyof typeof HORIZON_AT;

/** Stop-aware R. From the stop day on the result is −1R. */
export function realizedR(outcome: WindowOutcome | undefined, field: HorizonField): number | null {
  if (!outcome || outcome.qualified === 0) return null;
  const at = HORIZON_AT[field];
  if (outcome.stopped && outcome.stop_day != null && outcome.stop_day <= at) return outcome.stop_ret ?? -1;
  const value = outcome[field];
  return value == null ? null : value;
}

export function returnTone(value: number | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

function checkInOrder(row: MorningRow, mode: CheckIn): number {
  const outcome = row.windows[mode];
  if (!outcome || outcome.qualified === 0 || outcome.rank == null || outcome.rank >= 100) return 1000;
  return outcome.rank;
}

export function orderedRows(rows: MorningRow[], mode: MorningMode): MorningRow[] {
  if (mode === "leaders") return [...rows].sort((a, b) => a.rank - b.rank || a.symbol.localeCompare(b.symbol));
  return [...rows].sort((a, b) => checkInOrder(a, mode) - checkInOrder(b, mode) || a.rank - b.rank);
}

export function shownRank(row: MorningRow, mode: MorningMode): number | null {
  if (mode === "leaders") return row.rank;
  const outcome = row.windows[mode];
  if (!outcome || outcome.qualified === 0 || outcome.rank == null || outcome.rank >= 100) return null;
  return outcome.rank;
}

export function outcomeLine(outcome: WindowOutcome | undefined): string {
  if (!outcome) return "No print at this time";
  if (outcome.qualified === 0) {
    return outcome.cross_time
      ? `Crossed at ${displayTime(outcome.cross_time)}, no fill at this check-in`
      : "Has not closed above the 20 RMA";
  }
  const hold = [
    `EOD ${signedR(realizedR(outcome, "eod_ret"))}`,
    `+1d ${signedR(realizedR(outcome, "d1_ret"))}`,
    `+3d ${signedR(realizedR(outcome, "d3_ret"))}`,
    `+5d ${signedR(realizedR(outcome, "d5_ret"))}`,
  ];
  if (outcome.cross_time) hold.unshift(`crossed ${displayTime(outcome.cross_time)}`);
  if (outcome.mfe != null) hold.push(`MFE ${signedR(outcome.mfe)}`);
  if (outcome.stopped) {
    const when = outcome.stop_day === 0 ? "same day" : `day +${outcome.stop_day}`;
    hold.push(`stopped ${when} (${signedR(outcome.stop_ret ?? -1)}${outcome.gapped ? ", gapped" : ""})`);
  } else if (outcome.eod_ret != null) {
    hold.push("stop not hit");
  }
  return hold.join(" · ");
}

const HORIZON_WORD: Record<string, string> = { eod: "the close", d1: "day 1", d2: "day 2", d3: "day 3", d4: "day 4", d5: "day 5" };

/** One sentence for the summary panel. The result is stop-aware R; 1R is 1% of the entry. */
export function bestSentence(best: BestWindow | null): string | null {
  if (!best) return null;
  const when = HORIZON_WORD[best.horizon] ?? best.horizon;
  const win = best.win_rate == null ? "" : ` ${Math.round(best.win_rate * 100)}% of fills were ahead by ${when}.`;
  const gaps = best.gap_count == null ? "" : ` ${best.gap_count} gapped through.`;
  const stop =
    best.stop_hit_rate == null
      ? ""
      : ` A 1% stop was hit ${Math.round(best.stop_hit_rate * 100)}% of the time (expectancy ${signedR(best.expectancy, 2)} per trade).`;
  return `Buying the names above the 20 RMA at the ${displayTime(best.window)} close returned ${signedR(best.avg, 2)} on average by ${when}.${win}${stop}${gaps}`;
}
