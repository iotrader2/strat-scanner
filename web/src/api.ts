export type Tf = "M" | "W" | "D";
export type Strat = "1" | "2U" | "2D" | "3" | null;

export interface Setup {
  kind: string;
  label: string;
  trigger: number;
  triggered: boolean;
  detail: string;
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
  leader_status: LeaderStatus;
  is_leader: boolean;
  leadership: Leadership;
  tightness: TightnessInfo | null;
  kill_candle: KillCandleInfo | null;
  /** A recent weekly breakout of a tight base on heavy volume (null when there is none). */
  breakout: BreakoutInfo | null;
  kind: "stock" | "etf" | "theme";
  indexes: string;
  in_universe: boolean;
  price: number;
  change_pct: number;
  avg_dollar_volume: number;
  avg_volume: number;
  as_of: string;
  score: number;
  score_raw: number;
  score_max_raw: number;
  score_breakdown: ScoreComponent[];
  full_continuity: boolean;
  mw_green: boolean;
  monthly_2u: boolean;
  has_setup: boolean;
  trigger: number | null;
  trigger_tf: Tf | null;
  setup: string | null;
  triggered: boolean | null;
  trigger_distance_pct: number | null;
  /** For names with no weekly setup: the closest weekly high above price (this or last week's high). */
  nearest_trigger: number | null;
  nearest_trigger_label: string | null;
  nearest_trigger_distance_pct: number | null;
  reason: string;
  tf: Record<Tf, TfState | null>;
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

export interface Status {
  last_refresh: string | null;
  /** Set when the server runs on history cut off at a past date (STRAT_AS_OF). */
  as_of: string | null;
  refreshing: boolean;
  progress: { done: number; total: number; message: string };
  error: string | null;
  symbols_cached: number;
  universe_size: number;
}

export interface AppConfig {
  min_price: number;
  min_dollar_volume: number;
  /** Relative-strength percentile (0..1) a name needs to count as a leader. */
  leader_min_rs: number;
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

export interface IssueCounts {
  advancing: number;
  declining: number;
  unchanged: number;
}

export interface Breadth {
  nasi: Nasi | null;
  fear_greed: FearGreed | null;
  issues: { nasdaq?: IssueCounts; nyse?: IssueCounts } | null;
}

export type TrendCall = "on" | "off" | "caution";

export interface TrendAverage {
  period: number;
  value: number;
  above: boolean;
}

export interface TrendIndex {
  symbol: string;
  price: number;
  averages: TrendAverage[];
}

/** QQQ, SPY and IWM versus their 10, 20 and 50 day averages. */
export interface Trend {
  call: TrendCall;
  indexes: TrendIndex[];
}

/** QQQ, SPY or IWM card on State of the Market. */
export interface MarketEtf {
  symbol: string;
  name: string;
  sector: string;
  group: "benchmark";
  row: ScanRow;
  candles: ChartCandle[];
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
  /** Theme cards, strongest first. */
  themes: (tf: Tf, bars = 60) => get<{ tf: Tf; as_of: string | null; themes: ThemeCard[] }>(`/api/themes?tf=${tf}&bars=${bars}`),
  /** QQQ, SPY and IWM for the State of the Market tab. */
  market: (tf: Tf, bars = 60) =>
    get<{ tf: Tf; as_of: string | null; etfs: MarketEtf[]; trend: Trend | null }>(`/api/market?tf=${tf}&bars=${bars}`),
  /** $NASI, Fear & Greed and advancers vs decliners. */
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
};

function send<T>(url: string, method: string, body: unknown): Promise<T> {
  return get<T>(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

/** Entry details; omitted price/date default to the last price and today on the server. */
export interface PositionInput {
  entry_price?: number | null;
  shares?: number | null;
  entry_date?: string | null;
}

export interface Position {
  symbol: string;
  entry_price: number;
  shares: number | null;
  entry_date: string;
  /** Live scan row; null until the symbol has cached data. */
  row: ScanRow | null;
}

export interface Positions {
  symbols: string[];
  positions: Position[];
}

export interface Watchlist {
  symbols: string[];
  rows: ScanRow[];
  missing: string[];
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
