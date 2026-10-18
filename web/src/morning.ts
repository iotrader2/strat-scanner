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
  single_entry?: SingleEntryStats;
  strat_reversal?: StratStats;
  cross_trigger?: CrossStats;
  ema_reclaim?: ReclaimStats;
}

export interface SingleHorizon {
  n_days: number;
  n_trades: number;
  avg_pct: number | null;
  avg_r: number | null;
  win_rate: number | null;
  stop_hit_rate: number | null;
  gap_count: number | null;
  total_r: number | null;
  expectancy: number | null;
  avg_mfe: number | null;
  median_r: number | null;
  best_r: number | null;
  worst_r: number | null;
  median_pct: number | null;
  best_pct: number | null;
  worst_pct: number | null;
  vs_qqq: number | null;
}

export interface SingleBook {
  id: string;
  label: string;
  rule: string;
  n_fills: number;
  avg_entry: string | null;
  median_entry?: string | null;
  avg_stop_pct: number | null;
  horizons: Record<string, SingleHorizon>;
}

export interface SingleEntryStats {
  books: Record<string, SingleBook>;
  order: string[];
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

export const SINGLE_HORIZONS = ["eod", "d1", "d2", "d3", "d4", "d5"] as const;

export const SINGLE_METRICS: { key: keyof SingleHorizon; label: string; kind: "count" | "pct" | "r" | "rate" | "r1" }[] = [
  { key: "n_days", label: "Days", kind: "count" },
  { key: "n_trades", label: "Fills", kind: "count" },
  { key: "avg_pct", label: "Avg %", kind: "pct" },
  { key: "avg_r", label: "Avg R", kind: "r" },
  { key: "win_rate", label: "Win", kind: "rate" },
  { key: "stop_hit_rate", label: "Stop", kind: "rate" },
  { key: "gap_count", label: "Gaps", kind: "count" },
  { key: "total_r", label: "Total R", kind: "r1" },
  { key: "expectancy", label: "Expectancy", kind: "r" },
  { key: "avg_mfe", label: "Avg MFE", kind: "r" },
  { key: "median_r", label: "Median R", kind: "r" },
  { key: "best_r", label: "Best R", kind: "r" },
  { key: "worst_r", label: "Worst R", kind: "r" },
  { key: "median_pct", label: "Median %", kind: "pct" },
  { key: "best_pct", label: "Best %", kind: "pct" },
  { key: "worst_pct", label: "Worst %", kind: "pct" },
  { key: "vs_qqq", label: "vs QQQ", kind: "pct" },
];

export const SINGLE_RULES = [
  { title: "10:30 close, above the 20 RMA", books: ["rma_all", "rma_first"] },
  { title: "First close above the 20 EMA", books: ["ema_all", "ema_first"] },
] as const;

/** Where the book actually got in, and how far the stop sits under that price. */
export function entryNote(book: SingleBook | StratBook | CrossBook | ReclaimBook | undefined): string {
  if (!book) return "";
  const when = book.avg_entry ?? "—";
  const clock = book.median_entry && book.median_entry !== book.avg_entry ? `${when} on average (median ${book.median_entry})` : when;
  const stop = book.avg_stop_pct == null ? "—" : `${Math.abs(book.avg_stop_pct).toFixed(2)}%`;
  return `${book.label} enters at ${clock}. The stop averages ${stop} under the entry.`;
}

export interface StratHorizon extends SingleHorizon {
  vs_rma_first: number | null;
}

export interface StratBook {
  id: string;
  label: string;
  title: string;
  timeframe: number;
  n_fills: number;
  avg_entry: string | null;
  median_entry?: string | null;
  avg_stop_pct: number | null;
  pattern_counts: Record<string, number>;
  finished_2u_rate: number | null;
  horizons: Record<string, StratHorizon>;
}

export interface StratStats {
  books: Record<string, StratBook>;
  order: string[];
  panels: { title: string; books: string[] }[];
  best: { id: string; label: string; avg_r: number | null; n_days: number; n_trades: number; vs_rma_first: number | null } | null;
  benchmark: { label: string; avg_r: number | null; n_days: number; n_trades: number } | null;
  definition: string;
}

export const STRAT_PATTERNS = ["2d-2u", "2d-1-2u", "3-1-2u", "1-2d-2u"] as const;

export const STRAT_METRICS: { key: keyof StratHorizon; label: string; kind: "count" | "pct" | "r" | "rate" | "r1" }[] = [
  ...SINGLE_METRICS,
  { key: "vs_rma_first", label: "vs 10:30 first", kind: "r" },
];

/** Pattern mix for one Strat book, plus how often the entry candle actually finished as a 2U. */
export function stratNote(book: StratBook | undefined): string {
  if (!book) return "";
  const counts = STRAT_PATTERNS.map((name) => `${name} ${book.pattern_counts?.[name] ?? 0}`).join(", ");
  const share = book.finished_2u_rate == null ? "—" : `${Math.round(book.finished_2u_rate * 100)}%`;
  return `${entryNote(book)} ${counts}. Finished as 2U: ${share}.`;
}

/** Day-3 winner among the eight Strat books, set next to the 10:30 first-name RMA book. */
export function stratSentence(stats: StratStats | undefined): string | null {
  const best = stats?.best;
  if (!best || best.avg_r == null) return null;
  const bench = stats?.benchmark?.avg_r;
  const benchText = bench == null ? "" : ` The 10:30 first-name RMA book is ${signedR(bench, 2)} by day 3.`;
  const paired = best.vs_rma_first == null ? "" : ` Paired against that book it is ${signedR(best.vs_rma_first, 2)}.`;
  return `${best.label} is the best of these books by day 3 at ${signedR(best.avg_r, 2)} per morning.${benchText}${paired}`;
}

export interface CrossBook {
  id: string;
  label: string;
  rule: string;
  n_fills: number;
  avg_entry: string | null;
  median_entry?: string | null;
  avg_stop_pct: number | null;
  opened_above: number;
  opened_above_rate: number | null;
  trades_per_day: number | null;
  tape_days: number;
  horizons: Record<string, StratHorizon>;
}

export interface CrossStats {
  books: Record<string, CrossBook>;
  order: string[];
  best: { id: string; label: string; avg_r: number | null; n_days: number; n_trades: number; vs_rma_first: number | null } | null;
  benchmark: { label: string; avg_r: number | null; n_days: number; n_trades: number } | null;
  definition: string;
}

/** How many fills were already above the average at the 9:30 open, and how many trades a tape day produced. */
export function crossNote(book: CrossBook | undefined): string {
  if (!book) return "";
  const per = book.trades_per_day == null ? "—" : book.trades_per_day.toFixed(1);
  return `${entryNote(book)} ${book.opened_above} of ${book.n_fills} opened above the average. ${per} trades per day.`;
}

/** Day-3 winner among the RMA, SMA, and EMA cross books, set next to the 10:30 first-name RMA book. */
export function crossSentence(stats: CrossStats | undefined): string | null {
  const best = stats?.best;
  if (!best || best.avg_r == null) return null;
  const bench = stats?.benchmark?.avg_r;
  const benchText = bench == null ? "" : ` The 10:30 first-name RMA book is ${signedR(bench, 2)} by day 3.`;
  const paired = best.vs_rma_first == null ? "" : ` Paired against that book it is ${signedR(best.vs_rma_first, 2)}.`;
  return `${best.label} is the best of these books by day 3 at ${signedR(best.avg_r, 2)} per morning.${benchText}${paired}`;
}

export interface ReclaimBook {
  id: string;
  label: string;
  title: string;
  rule: string;
  n_fills: number;
  avg_entry: string | null;
  median_entry?: string | null;
  avg_stop_pct: number | null;
  trades_per_day: number | null;
  tape_days: number;
  horizons: Record<string, StratHorizon>;
}

export interface ReclaimStats {
  books: Record<string, ReclaimBook>;
  order: string[];
  panels: { title: string; books: string[] }[];
  best: { id: string; label: string; avg_r: number | null; n_days: number; n_trades: number; vs_rma_first: number | null } | null;
  benchmark: { label: string; avg_r: number | null; n_days: number; n_trades: number } | null;
  definition: string;
}

/** Entry clock and stop distance for one EMA pullback-reclaim book, plus trades per tape day. */
export function reclaimNote(book: ReclaimBook | undefined): string {
  if (!book) return "";
  const per = book.trades_per_day == null ? "—" : book.trades_per_day.toFixed(1);
  return `${entryNote(book)} ${per} trades per day.`;
}

/** Day-3 winner among the six reclaim books, set next to the 10:30 first-name RMA book. */
export function reclaimSentence(stats: ReclaimStats | undefined): string | null {
  const best = stats?.best;
  if (!best || best.avg_r == null) return null;
  const bench = stats?.benchmark?.avg_r;
  const benchText = bench == null ? "" : ` The 10:30 first-name RMA book is ${signedR(bench, 2)} by day 3.`;
  const paired = best.vs_rma_first == null ? "" : ` Paired against that book it is ${signedR(best.vs_rma_first, 2)}.`;
  return `${best.label} is the best of these books by day 3 at ${signedR(best.avg_r, 2)} per morning.${benchText}${paired}`;
}
