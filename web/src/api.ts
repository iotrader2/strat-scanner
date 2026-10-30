export type Tf = "M" | "W" | "D";
/** Quarterly and half-year Strat tags shown on the index cards. */
export type HigherTf = "3M" | "6M";
export type Strat = "1" | "2U" | "2D" | "3" | null;

export interface Setup {
  kind: string;
  label: string;
  trigger: number;
  triggered: boolean;
  detail: string;
  /** Broken during the week still in progress (the trigger itself is last completed week's). */
  live?: boolean;
}

export interface CandlePatternBar {
  inside: boolean;
  hammer: boolean;
  /** Date of that bar (week start for weekly). */
  date: string | null;
}

export interface TfState {
  tf: Tf;
  strat: Strat;
  prev_strat: Strat;
  color: "green" | "red" | "flat";
  open: number;
  high: number;
  low: number;
  close: number;
  inside: boolean;
  hammer: boolean;
  /** Continuity of the bar in progress (current month / week / today): price vs its open. Absent on 3M / 6M. */
  live_color?: "green" | "red" | "flat" | null;
  live_open?: number | null;
}

export type LeaderStatus = "leader" | "broken" | "laggard";

export interface Leadership {
  rs: number | null;
  status: LeaderStatus;
  /** Return minus QQQ, in percentage points, per period. */
  excess: Perf;
  above_ma: Record<"10" | "20" | "50", boolean | null>;
  off_52w_high_pct: number | null;
  off_6m_high_pct: number | null;
  /** "none", "warning" (weakening) or "broken" (trend lost: demoted and left off the leaders list). */
  breakdown: "none" | "warning" | "broken";
  breakdown_reasons: string[];
  /** Set when the breakdown level just worsened (none -> warning/broken or warning -> broken) within the last 3 sessions. */
  breakdown_new?: BreakdownChange | null;
  /** Set when a leader crossed above P90 within the last 3 sessions and is not broken. */
  leader_new?: LeaderEntry | null;
}

export interface BreakdownChange {
  from: "none" | "warning";
  to: "warning" | "broken";
  /** First session at the new (or a worse) level. */
  since: string;
  /** Sessions before the latest one (0 = today). */
  sessions_ago: number;
}

export interface LeaderEntry {
  /** First session back at or above the RS gate. */
  since: string;
  sessions_ago: number;
  /** Blended RS just before it crossed (0..1). */
  from_rs: number;
}

export interface KillCandleInfo {
  date: string;
  age: number;
  range_x_atr: number;
  volume_x: number;
  close_position: number;
  reclaimed: boolean;
  /** Share of the score removed now (after fading); 0 once price has reclaimed the candle's high. */
  penalty: number;
}

/** A recent weekly breakout that has since closed back below its base high. */
export interface FailedBreakoutInfo {
  /** First trading day of the breakout week. */
  week: string;
  weeks_ago: number;
  base_weeks: number;
  /** The base high the breakout cleared (the breakout level). */
  level: number;
  volume_x: number;
  breakout_close: number;
  /** First close below the level in the current run below it. */
  failed_on: string;
  sessions_below: number;
  close: number;
  /** Latest close vs the level, % (negative). */
  below_pct: number;
  /** Deepest close since the breakout vs the level, %. */
  low_pct: number;
}

export interface BreakoutInfo {
  /** First trading day of the breakout week. */
  week: string;
  weeks_ago: number;
  base_weeks: number;
  base_high: number;
  volume_x: number;
  close_position: number;
  close: number;
}

export interface TightnessInfo {
  range10_pct: number;
  range50_pct: number;
  ratio: number;
  contraction: number;
  fraction: number;
}

export interface ScoreComponent {
  key: string;
  label: string;
  points: number;
  max_points: number;
  /** Share of the 100-point score this line is worth (max points / max raw points, in percent). */
  weight_pct: number;
  /** Internal weighting, e.g. "1M 20%" for relative strength or "52-week high 6 pts" for near highs. */
  sub_weights: string[];
  detail: string;
}

export interface ScanRow {
  symbol: string;
  name: string;
  sector: string;
  sector_etf: string;
  /** GICS sub-industry, ICB subsector or Yahoo industry ("" for ETFs). */
  industry?: string;
  /** Primary theme id and name (null for ETFs and stocks no theme lists). */
  theme?: string | null;
  theme_name?: string | null;
  /** Other themes that list the stock as a secondary member (shown on their cards and matched by the theme filter). */
  secondary_themes?: string[];
  secondary_theme_names?: string[];
  /** Standing of the primary theme on the Themes page, which drives the Theme strength points. */
  theme_strength?: ThemeStrength | null;
  /** Price return in percent over the last 1, 3 and 6 months (null while the history is too short). */
  perf: Perf;
  /** Blended 1M/3M/6M return percentile among peers (0..1); null while the history is too short. */
  rs: number | null;
  /** The same blended RS percentile (0..1) as of 5 sessions earlier, ranked among peers on that date; null without history. */
  rs_prev?: number | null;
  rs_prev_date?: string | null;
  /** Change in whole percentile points between the two chip values (RS 91 vs RS 98 = -7). */
  rs_change?: number | null;
  leader_status: LeaderStatus;
  is_leader: boolean;
  /** Close divided by QQQ made a 52-week high in the last 5 sessions. False when QQQ was not loaded. */
  rs_line_high?: boolean;
  leadership: Leadership;
  tightness: TightnessInfo | null;
  kill_candle: KillCandleInfo | null;
  /** A recent weekly breakout of a tight base on heavy volume (null when there is none). */
  breakout: BreakoutInfo | null;
  /** The latest breakout of the last 8 weeks that has since closed back below its base high (null when there is none). */
  failed_breakout?: FailedBreakoutInfo | null;
  kind: "stock" | "etf" | "theme";
  indexes: string;
  in_universe: boolean;
  price: number;
  change_pct: number;
  avg_dollar_volume: number;
  avg_volume: number;
  /** 14-day average true range, in dollars. */
  atr?: number | null;
  /** ATR as a percent of the last close. */
  atr_pct?: number | null;
  /** Percent distance of price from the daily 6 / 20 / 50 SMA, (price - SMA) / SMA * 100; null when there are too few bars. */
  ma_dist_pct?: Partial<Record<"6" | "20" | "50", number | null>> | null;
  as_of: string;
  score: number;
  score_raw: number;
  score_max_raw: number;
  score_breakdown: ScoreComponent[];
  full_continuity: boolean;
  mw_green: boolean;
  monthly_2u: boolean;
  has_setup: boolean;
  /**
   * Daily MACD (6,20,9) histogram trigger on the most recent daily bar.
   * "bullish" is the first green bar after 3+ red; "bearish" is the first red after 3+ green.
   * Null when the latest bar is not that flip. Absent on a scan cached before this field existed.
   */
  /** Daily bullish / bearish trend change setup: the MACD trigger below, with the close on the matching side of the 50-day SMA. */
  daily_trend?: "bullish" | "bearish" | null;
  /** Raw daily MACD (6,20,9) histogram trigger on the latest bar, the same as the chart arrow (no 50-day check). */
  daily_macd_trigger?: "bullish" | "bearish" | null;
  /** Weekly bullish / bearish trend change setup: the same MACD trigger on the current (in-progress) weekly bar, with the latest close on the matching side of the 10-week SMA. */
  weekly_trend?: "bullish" | "bearish" | null;
  /** Raw weekly MACD (6,20,9) histogram trigger on the current week, the same as the weekly chart arrow (no 10-week check). */
  weekly_macd_trigger?: "bullish" | "bearish" | null;
  trigger: number | null;
  trigger_tf: Tf | null;
  setup: string | null;
  /** Inside bar / hammer on the last completed weekly and daily bar (the Candle Pattern filter). */
  candle_patterns?: { W: CandlePatternBar | null; D: CandlePatternBar | null } | null;
  triggered: boolean | null;
  /** True when the in-progress week traded above the trigger (set from the last completed week). */
  triggered_live?: boolean | null;
  trigger_distance_pct: number | null;
  /** For names with no weekly setup: the closest completed-week high above price. */
  reason: string;
  tf: Record<Tf, TfState | null> & Partial<Record<HigherTf, TfState | null>>;
  earnings?: Earnings | null;
  setups?: (Setup & { tf: Tf; points: number })[];
}

export type PerfPeriod = "1m" | "3m" | "6m";
export type Perf = Record<PerfPeriod, number | null>;

export interface ThemeStrength {
  theme: string;
  name: string;
  score: number;
  rank: number;
  total: number;
  points: number;
}

export interface Earnings {
  date: string;
  date_end: string | null;
  timing: "BMO" | "AMC" | null;
  days_until: number;
}

export interface ChartCandle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  strat: Strat;
  hammer: boolean;
}

/** One regular-session 15-minute bar. ``time`` is unix seconds (UTC). EMAs are null until that period has a full seed. */
export interface IntradayBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  ema: Partial<Record<"6" | "20" | "50" | "120", number | null>>;
}

/** 15-minute chart for one symbol. Bars are the last few sessions; the 120 EMA was seeded on ``seed_sessions``. */
export interface IntradayChartData {
  symbol: string;
  /** Always the regular session. Premarket bars are not included. */
  session: "regular";
  bar_minutes: number;
  time_zone: string;
  display_sessions: number;
  seed_sessions: number;
  /** How many of those sessions are actually in ``bars`` (shorter when history is thin). */
  sessions: number;
  bars: IntradayBar[];
}

export interface Status {
  last_refresh: string | null;
  /** Set when the server runs on history cut off at a past date (STRAT_AS_OF). */
  as_of: string | null;
  refreshing: boolean;
  /** Same as refreshing: the background fetcher is downloading or recomputing. */
  updating?: boolean;
  progress: { done: number; total: number; message: string };
  error: string | null;
  symbols_cached: number;
  universe_size: number;
  /** Bumps when a new scan snapshot is published. */
  version?: number;
  computed_at?: string | null;
  /** Quote delay from the provider: "5m" (Alpaca IEX 5-minute bars, real-time prices) or "15m" (Yahoo). */
  delay?: string;
  /** Price source: "alpaca" or "yahoo". */
  source?: string;
}

export interface AppConfig {
  min_price: number;
  min_dollar_volume: number;
  /** Relative-strength percentile (0..1) a name needs to count as a leader. */
  leader_min_rs: number;
  /** The Leaders scan also needs a score strictly above this (70). */
  leaders_min_score?: number;
  themes: ThemeInfo[];
}

export interface ThemeInfo {
  id: string;
  name: string;
  /** Primary plus secondary members. */
  count: number;
}

export interface NasiPoint {
  time: string;
  value: number;
}

/** Nasdaq McClellan Summation Index ($NASI). */
export interface Nasi {
  value: number;
  change: number | null;
  as_of: string;
  points: NasiPoint[];
}

/** CNN Fear & Greed index, 0 (extreme fear) to 100 (extreme greed). */
export interface FearGreed {
  score: number;
  rating: string;
  previous_close: number | null;
  previous_week: number | null;
  previous_month: number | null;
}

/** Up, down and unchanged names in the scanner's universe. */
export interface IssueCounts {
  advancing: number;
  declining: number;
  unchanged: number;
  /** Names included in the count. */
  names: number;
}

/** 52-week new highs and new lows in the same universe. */
export interface HighLowCounts {
  highs: number;
  lows: number;
  names: number;
}

/** Exchange-wide Nasdaq issues from the WSJ markets diary, for the same session as the universe counts. */
export interface NasdaqIssues {
  advancing: number;
  declining: number;
  unchanged: number;
  /** The diary's own stamp, e.g. "4:15 PM EDT 10/22/26". */
  as_of: string;
  /** Session date (YYYY-MM-DD). */
  session: string;
}

/** Exchange-wide Nasdaq 52-week new highs and new lows, from the same WSJ diary request. */
export interface NasdaqHighsLows {
  highs: number;
  lows: number;
  /** The diary's own stamp, e.g. "4:15 PM EDT 10/22/26". */
  as_of: string;
  /** Session date (YYYY-MM-DD). */
  session: string;
}

export interface Breadth {
  nasi: Nasi | null;
  fear_greed: FearGreed | null;
  issues: IssueCounts | null;
  highs_lows: HighLowCounts | null;
  /** Missing when the diary could not be read for this session: the row is hidden, never estimated. */
  nasdaq_issues?: NasdaqIssues | null;
  /** Same rule: hidden when the diary could not be read for this session. */
  nasdaq_highs_lows?: NasdaqHighsLows | null;
}

export type TrendCall = "on" | "off" | "caution";

export interface TrendAverage {
  period: number;
  value: number;
  above: boolean;
}

export interface TrendIndex {
  symbol: string;
  /** The price the card shows (premarket / after-hours quote when active, else the last close). */
  price: number;
  averages: TrendAverage[];
  /** Market-score points: how many of the 6/20/50 averages the price is above (0–3). */
  points: number;
  max_points: number;
}

/** QQQ, SPY and IWM versus their 6, 20 and 50 day simple averages, plus the market score out of 9. */
export interface Trend {
  call: TrendCall;
  indexes: TrendIndex[];
  score: number;
  score_max: number;
}

/** QQQ, SPY or IWM card on State of the Market. */
export interface MarketEtf {
  symbol: string;
  name: string;
  sector: string;
  group: "benchmark";
  row: ScanRow;
  candles: ChartCandle[];
  /** Set while the card shows an extended-hours price instead of the regular session. */
  session: "premarket" | "after_hours" | null;
}

export interface ThemeChip {
  symbol: string;
  name: string;
  change_pct: number;
  perf: Perf;
  score: number;
  mw_green: boolean;
  has_setup: boolean;
  /** Secondary member: shown dimmed, not part of the theme index. */
  also: boolean;
}

/** One theme: its equal-weight index (row + candles) and member chips. */
export interface ThemeCard {
  id: string;
  name: string;
  description: string;
  /** Primary members (the ones in the index). */
  count: number;
  members: ThemeChip[];
  also: ThemeChip[];
  row: ScanRow;
  candles: ChartCandle[];
}

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** FastAPI errors: `detail` is a string, or a list of `{msg}` objects for validation failures. */
export function errorDetail(body: unknown): string | null {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d as { msg?: unknown })?.msg).filter((m): m is string => typeof m === "string");
    return msgs.length ? msgs.join("; ") : null;
  }
  return null;
}

async function get<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      detail = errorDetail(JSON.parse(text)) ?? text;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail || `${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  status: () => get<Status>("/api/status"),
  config: () => get<AppConfig>("/api/config"),
  refresh: (full = false) => get<{ started: boolean }>(`/api/refresh?full=${full}`, { method: "POST" }),
  // Liquidity and leadership filters are applied on the client, so fetch every name once.
  scan: () =>
    get<{ as_of: string | null; count: number; rows: ScanRow[] }>("/api/scan?min_price=0&min_dollar_volume=0&leaders_only=false"),
  symbol: (symbol: string) =>
    get<{ row: ScanRow; charts: Record<Tf, ChartCandle[]> }>(`/api/symbol/${encodeURIComponent(symbol)}`),
  /** Regular-session 15-minute candles and 6/20/50/120 EMAs. One ticker, fetched when its chart opens. */
  bars15m: (symbol: string) => get<IntradayChartData>(`/api/symbol/${encodeURIComponent(symbol)}/bars15m`),
  /** Theme cards, strongest first. */
  themes: (tf: Tf, bars = 60) => get<{ tf: Tf; as_of: string | null; themes: ThemeCard[] }>(`/api/themes?tf=${tf}&bars=${bars}`),
  /** QQQ, SPY and IWM for the State of the Market tab. */
  market: (tf: Tf | HigherTf, bars = 60) =>
    get<{ tf: Tf | HigherTf; as_of: string | null; etfs: MarketEtf[]; trend: Trend | null }>(`/api/market?tf=${tf}&bars=${bars}`),
  /** $NASI, Fear & Greed, and breadth of the symbols the scanner tracks. */
  breadth: () => get<Breadth>("/api/breadth"),
  watchlist: () => get<Watchlist>("/api/watchlist"),
  watch: (symbol: string) =>
    get<Watchlist>("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    }),
  unwatch: (symbol: string) => get<Watchlist>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  positions: () => get<Positions>("/api/positions"),
  openPosition: (req: PositionInput & { symbol: string }) => send<Positions>("/api/positions", "POST", req),
  updatePosition: (symbol: string, req: Required<Pick<PositionInput, "entry_price" | "entry_date">> & Pick<PositionInput, "shares">) =>
    send<Positions>(`/api/positions/${encodeURIComponent(symbol)}`, "PUT", req),
  closePosition: (symbol: string) => get<Positions>(`/api/positions/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  positionToWatchlist: (symbol: string) =>
    get<Positions>(`/api/positions/${encodeURIComponent(symbol)}/watchlist`, { method: "POST" }),
  trimPosition: (symbol: string, req: { shares: number; price: number }) =>
    send<Positions>(`/api/positions/${encodeURIComponent(symbol)}/trims`, "POST", req),
  undoTrim: (symbol: string, trimId: number) =>
    get<Positions>(`/api/positions/${encodeURIComponent(symbol)}/trims/${trimId}`, { method: "DELETE" }),
  /** One session's setup alerts (default today), newest first. */
  alerts: (session?: string) => get<AlertsPayload>(`/api/alerts${session ? `?session=${encodeURIComponent(session)}` : ""}`),
  /** One archived session. No date uses the latest archived day, or the previous weekday. */
  alertHistory: (date?: string) =>
    get<AlertHistoryPayload>(`/api/alerts/history${date ? `?date=${encodeURIComponent(date)}` : ""}`),
  /** Acknowledge alerts; no ids acknowledges every unread one. */
  ackAlerts: (ids?: number[]) => send<{ acknowledged: number; unread: number }>("/api/alerts/ack", "POST", { ids: ids ?? null }),
  alertMetrics: (q: { start?: string; end?: string; symbol?: string }) => {
    const params = new URLSearchParams();
    if (q.start) params.set("start", q.start);
    if (q.end) params.set("end", q.end);
    if (q.symbol) params.set("symbol", q.symbol);
    const qs = params.toString();
    return get<AlertMetricsPayload>(`/api/alerts/metrics${qs ? `?${qs}` : ""}`);
  },
  alertSettings: () => get<AlertSettingsPayload>("/api/alerts/settings"),
  saveAlertSettings: (changes: Partial<AlertSettings>) => send<AlertSettingsPayload>("/api/alerts/settings", "PUT", changes),
  resetAlertSettings: () => get<AlertSettingsPayload>("/api/alerts/settings", { method: "DELETE" }),
};

export type AlertSetup = "A" | "B" | "C" | "D" | "E" | "F";
export type AlertStatus = "pending" | "triggered" | "stopped" | "breakeven" | "exited" | "expired" | "cancelled";

/** One setup alert and what happened after it. Times are UTC ISO; the UI shows them in Phoenix time. */
export interface TradeAlert {
  id: number;
  symbol: string;
  session: string;
  setup: AlertSetup;
  /** Start of the setup bar; the alert fires when that bar closes (fired_at). */
  setup_bar: string;
  fired_at: string;
  detected_at: string;
  /** Found after the fact (restart or a missed poll): shown, but no chime. */
  late: boolean;
  top: boolean;
  trigger_price: number;
  stop_price: number;
  setup_low: number;
  setup_high: number;
  ref_price: number;
  status: AlertStatus;
  filled: boolean;
  fill_price: number | null;
  fill_at: string | null;
  high_reached: number | null;
  stop_hit: boolean;
  breakeven_at: string | null;
  exit_price: number | null;
  exit_at: string | null;
  exit_reason: string | null;
  r_multiple: number | null;
  details: {
    variant?: string;
    volume_ratio?: number | null;
    rearmed?: number;
    a_stop_capped?: boolean;
    /** 15-minute EMA 120 at the setup bar (about the 1-hour EMA 30) and the distance to it, in percent. */
    ema360?: number | null;
    ema360_close_pct?: number | null;
    ema360_low_pct?: number | null;
  };
  acknowledged: boolean;
  /** Scanner score for this symbol (the Stock Scanner pill). Null when the name is not in the current scan. */
  score: number | null;
  score_raw?: number | null;
  score_max_raw?: number | null;
  score_breakdown?: ScoreComponent[];
  /** Present when this stock reports inside the earnings warning window. Same object as a scan row. */
  earnings?: Earnings | null;
}

export interface AlertHistoryPayload {
  date: string;
  alerts: TradeAlert[];
  /** Archived trading dates, newest first. */
  dates: string[];
  setups: Record<AlertSetup, string>;
  ema5m: Record<string, Ema5m | null>;
}

export interface AlertsPayload {
  session: string;
  alerts: TradeAlert[];
  sessions: string[];
  unread: number;
  last_run: { at?: string; alerts?: number; symbols?: number };
  watchlist: string[];
  setups: Record<AlertSetup, string>;
  /**
   * Current live 15-minute 6/20 EMA for each alert symbol, from the lists poll already in memory.
   * Null when that name is not on the watchlist or in positions. Keyed by symbol, not by alert.
   */
  ema5m: Record<string, Ema5m | null>;
}

export interface AlertMetricRow {
  setup: AlertSetup | "All";
  name: string;
  count: number;
  filled: number;
  closed: number;
  open: number;
  fill_rate: number | null;
  win_rate: number | null;
  avg_r: number | null;
  total_r: number | null;
}

export interface AlertMetricsPayload {
  start: string | null;
  end: string | null;
  symbol: string | null;
  rows: AlertMetricRow[];
  symbols: string[];
}

export type AlertSettings = Record<string, number>;

export interface AlertSettingsPayload {
  settings: AlertSettings;
  defaults: AlertSettings;
  limits: Record<string, [number, number]>;
}

function send<T>(url: string, method: string, body: unknown): Promise<T> {
  return get<T>(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

/** Entry details; omitted price/date default to the last price and today on the server. */
export interface PositionInput {
  entry_price?: number | null;
  shares?: number | null;
  entry_date?: string | null;
}

export interface PositionTrim {
  id: number;
  shares: number;
  price: number;
  trimmed_at: string;
}

export interface Position {
  symbol: string;
  /** Initial buy price. Trims do not change it. */
  entry_price: number;
  /** Shares originally bought. Null until a share count is entered. */
  shares: number | null;
  entry_date: string;
  /** Shares still held (initial minus trims). Null when no share count was entered. */
  remaining_shares: number | null;
  /** Trim-adjusted cost basis. Equals the buy price when there are no trims; zero or negative is a free trade. */
  break_even: number;
  /** Realized P/L from trims versus the buy price. */
  realized_pnl: number;
  trims: PositionTrim[];
  /** Live scan row; null until the symbol has cached data. */
  row: ScanRow | null;
}

/** Premarket print for a watchlist / positions symbol (Alpaca). Null outside 04:00-16:00 ET or with no print. */
export interface PremarketPrint {
  session: string;
  price: number;
  /** UTC ISO time of the print (bar start for a SIP bar). */
  time: string;
  source: string;
  prev_close: number;
  change_pct: number;
  /** SIP volume since 04:00 ET; trails the price by about 15 minutes until final. */
  volume: number | null;
  volume_through: string | null;
  /** True once the exact premarket close and full premarket volume are in (about 09:46 ET). */
  final: boolean;
}

export type EmaSide = "above" | "below" | "at";

/** Price against the 6 and 20 EMA on the 15-minute chart (regular-session bars). */
export interface Ema5m {
  price: number;
  /** What the price is: the live 15-minute close, the premarket print, or the last regular close. */
  basis: "live" | "premarket" | "close";
  time: string;
  bar_time: string;
  ema6: number;
  ema20: number;
  vs6: EmaSide;
  vs20: EmaSide;
  /** EMAs the last completed bar closed back above (crossover); empty once the next bar completes. */
  highlight: number[];
  highlight_bar: string | null;
  highlight_until: string | null;
}

/** Low / high of the day (15-minute bars) with the latest price placed in it. */
export interface DayRange {
  low: number;
  high: number;
  last: number;
  /** 0 = at the low, 100 = at the high. */
  pct: number;
  /** Today's regular session so far, today's premarket so far, or the last completed session. */
  basis: "regular" | "premarket" | "last session";
  session: string;
}

export interface ListIntraday {
  premarket: PremarketPrint | null;
  ema5m: Ema5m | null;
  /** "6", "20" or "6+20" while a crossover is live, else null. */
  ema5m_cross: string | null;
  ema5m_cross_bar: string | null;
  /** Null when there is no data or the range is flat: the cell shows a dash. */
  day_range?: DayRange | null;
}

export interface Positions {
  symbols: string[];
  positions: Position[];
  intraday?: Record<string, ListIntraday>;
}

export interface Watchlist {
  symbols: string[];
  rows: ScanRow[];
  missing: string[];
  intraday?: Record<string, ListIntraday>;
}

export function fmtMoney(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(0)}`;
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}
