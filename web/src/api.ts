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

export interface ScoreComponent {
  key: string;
  label: string;
  points: number;
  max_points: number;
  detail: string;
}

export interface ScanRow {
  symbol: string;
  name: string;
  sector: string;
  sector_etf: string;
  kind: "stock" | "etf";
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
  reason: string;
  tf: Record<Tf, TfState | null>;
  earnings?: Earnings | null;
  setups?: (Setup & { tf: Tf; points: number })[];
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
  refreshing: boolean;
  progress: { done: number; total: number; message: string };
  error: string | null;
  symbols_cached: number;
  universe_size: number;
}

export interface AppConfig {
  min_price: number;
  min_dollar_volume: number;
  sectors: string[];
  sector_etfs: Record<string, string>;
}

export interface SectorEtf {
  symbol: string;
  name: string;
  sector: string;
  group: "spdr" | "industry" | "benchmark";
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

async function get<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
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
  // Liquidity filters are applied on the client, so fetch every weekly setup once.
  scan: () => get<{ as_of: string | null; count: number; rows: ScanRow[] }>("/api/scan?min_price=0&min_dollar_volume=0"),
  symbol: (symbol: string) =>
    get<{ row: ScanRow; charts: Record<Tf, ChartCandle[]> }>(`/api/symbol/${encodeURIComponent(symbol)}`),
  sectors: (tf: Tf, bars = 60) => get<{ tf: Tf; as_of: string | null; etfs: SectorEtf[] }>(`/api/sectors?tf=${tf}&bars=${bars}`),
  watchlist: () => get<Watchlist>("/api/watchlist"),
  watch: (symbol: string) =>
    get<Watchlist>("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    }),
  unwatch: (symbol: string) => get<Watchlist>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
};

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
