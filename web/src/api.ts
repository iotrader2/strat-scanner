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
  setups: Setup[];
}

export interface ScanRow {
  symbol: string;
  name: string;
  sector: string;
  sector_etf: string;
  kind: "stock" | "etf";
  indexes: string;
  price: number;
  change_pct: number;
  avg_dollar_volume: number;
  as_of: string;
  score: number;
  full_continuity: boolean;
  mw_green: boolean;
  trigger: number | null;
  trigger_tf: Tf | null;
  setup: string | null;
  triggered: boolean | null;
  trigger_distance_pct: number | null;
  reason: string;
  tf: Record<Tf, TfState | null>;
  setups?: (Setup & { tf: Tf; points: number })[];
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

async function get<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export const api = {
  status: () => get<Status>("/api/status"),
  config: () => get<AppConfig>("/api/config"),
  refresh: (full = false) => get<{ started: boolean }>(`/api/refresh?full=${full}`, { method: "POST" }),
  scan: (minPrice: number, minDollarVolume: number) =>
    get<{ as_of: string | null; count: number; rows: ScanRow[] }>(
      `/api/scan?min_price=${minPrice}&min_dollar_volume=${minDollarVolume}`,
    ),
  symbol: (symbol: string) =>
    get<{ row: ScanRow; charts: Record<Tf, ChartCandle[]> }>(`/api/symbol/${encodeURIComponent(symbol)}`),
  sectors: (tf: Tf, bars = 60) => get<{ tf: Tf; as_of: string | null; etfs: SectorEtf[] }>(`/api/sectors?tf=${tf}&bars=${bars}`),
};

export function fmtMoney(v: number): string {
  if (v >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  return `$${v.toFixed(0)}`;
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
}
