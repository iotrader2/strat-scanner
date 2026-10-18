/** Morning Leaders view helpers. The numbers come from the API; this only formats and orders them. */

export const CHECK_INS = ["09:45", "10:00", "10:15", "10:30", "10:45"] as const;
export type CheckIn = (typeof CHECK_INS)[number];
export type MorningMode = "leaders" | CheckIn;

export interface WindowOutcome {
  rank?: number;
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
}

export interface WindowStat {
  n_days: number;
  n_trades: number;
  horizons: Record<string, HorizonStat>;
  vs_open: Record<string, number | null>;
  vs_qqq: Record<string, number | null>;
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
  vs_open: number | null;
  vs_qqq: number | null;
}

export interface MorningStats {
  windows: Record<string, WindowStat>;
  qqq: Record<string, { n_days: number; n_trades: number; horizons: Record<string, HorizonStat> }>;
  best: BestWindow | null;
  primary_horizon: string;
  weights: { move: number; vs_qqq: number; opening_range: number };
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

export function returnTone(value: number | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

export function orderedRows(rows: MorningRow[], mode: MorningMode): MorningRow[] {
  if (mode === "leaders") return [...rows].sort((a, b) => a.rank - b.rank || a.symbol.localeCompare(b.symbol));
  return [...rows].sort((a, b) => {
    const left = a.windows[mode]?.rank ?? 100;
    const right = b.windows[mode]?.rank ?? 100;
    return left - right || a.rank - b.rank;
  });
}

export function shownRank(row: MorningRow, mode: MorningMode): number | null {
  if (mode === "leaders") return row.rank;
  const rank = row.windows[mode]?.rank;
  return rank == null ? null : rank;
}

export function outcomeLine(outcome: WindowOutcome | undefined): string {
  if (!outcome) return "No print at this time";
  const hold = [
    `EOD ${signedPct(outcome.eod_ret)}`,
    `+1d ${signedPct(outcome.d1_ret)}`,
    `+3d ${signedPct(outcome.d3_ret)}`,
    `+5d ${signedPct(outcome.d5_ret)}`,
  ];
  if (outcome.stopped) {
    const when = outcome.stop_day === 0 ? "same day" : `day +${outcome.stop_day}`;
    hold.push(`stopped ${when} (${signedPct(outcome.stop_ret)})`);
  } else if (outcome.eod_ret != null) {
    hold.push("stop not hit");
  }
  return hold.join(" · ");
}

const HORIZON_WORD: Record<string, string> = { eod: "the close", d1: "day 1", d2: "day 2", d3: "day 3", d4: "day 4", d5: "day 5" };

/** One sentence for the summary panel. The return is the close-to-close hold; the stop is named beside it. */
export function bestSentence(best: BestWindow | null): string | null {
  if (!best) return null;
  const when = HORIZON_WORD[best.horizon] ?? best.horizon;
  const win = best.win_rate == null ? "" : ` ${Math.round(best.win_rate * 100)}% of mornings were higher by ${when}.`;
  const stop =
    best.stop_hit_rate == null
      ? ""
      : ` A stop at that candle's low was hit ${Math.round(best.stop_hit_rate * 100)}% of the time (expectancy ${signedPct(best.expectancy)}).`;
  return `Buying the day's top 10 at the ${displayTime(best.window)} close returned ${signedPct(best.avg)} on average by ${when}.${win}${stop}`;
}
