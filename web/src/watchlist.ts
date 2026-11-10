import type { DailySetupRef, ScanRow } from "./api";

/** The watchlist after adding (on) or removing (off) a symbol, keeping insertion order. */
export function withSymbol(symbols: string[], symbol: string, on: boolean): string[] {
  if (on) return symbols.includes(symbol) ? symbols : [...symbols, symbol];
  return symbols.filter((s) => s !== symbol);
}

/** Rows for the symbols currently watched, so optimistic removals disappear before the API answers. */
export function watchedRows(rows: ScanRow[], symbols: string[]): ScanRow[] {
  const watched = new Set(symbols);
  return rows.filter((r) => watched.has(r.symbol));
}

export const NO_SETUP_LABEL = "no active setup";

/** Compact names for the watchlist Setup column. The stored row still keeps the full alert setup ref. */
const SETUP_SHORT: Record<string, string> = {
  "episodic-pivot": "EP",
  "delayed-hvc": "Delayed HVC",
  "delayed-hvc-short": "Delayed HVC",
  "flat-base-breakout": "Flat Base",
  "flat-base-breakdown": "Flat Base",
  "undercut-rally": "Undercut Rally",
  "overcut-fail": "Overcut Fail",
  "ma-undercut-rally": "MA Undercut",
  "ma-overcut-fail": "MA Overcut Fail",
  "high-tight-flag": "HTF",
  "low-tight-flag": "LTF",
  "ema-crossback": "EMA Crossback",
  "ema-crossback-short": "EMA Crossback",
  "wedge-pop": "Wedge Pop",
  "wedge-drop": "Wedge Drop",
  "gap-down-pivot": "Gap Down",
};

export interface WatchSetupGroup {
  side: "long" | "short";
  text: string;
}

/** One line per side. Several periods of the same setup collapse to "MA Overcut Fail 10/20". */
export function watchSetupGroups(setups: ReadonlyArray<Partial<DailySetupRef>> | null | undefined): WatchSetupGroup[] {
  const bySide = new Map<"long" | "short", Map<string, { name: string; periods: number[] }>>();
  for (const setup of setups ?? []) {
    const kind = setup.kind || setup.label;
    if (!kind) continue;
    const side = setup.side === "short" ? "short" : "long";
    const name = SETUP_SHORT[kind] || setup.label || kind;
    const groups = bySide.get(side) ?? new Map();
    bySide.set(side, groups);
    const entry = groups.get(kind) ?? { name, periods: [] };
    if (setup.period != null && Number.isFinite(setup.period) && !entry.periods.includes(setup.period)) {
      entry.periods.push(setup.period);
    }
    groups.set(kind, entry);
  }
  const out: WatchSetupGroup[] = [];
  for (const side of ["long", "short"] as const) {
    const groups = bySide.get(side);
    if (!groups) continue;
    const text = [...groups.values()]
      .map((entry) => (entry.periods.length ? `${entry.name} ${[...entry.periods].sort((a, b) => a - b).join("/")}` : entry.name))
      .join(", ");
    if (text) out.push({ side, text });
  }
  return out;
}

/** Trimmed, upper-cased ticker as typed into the Add symbol box ("" when blank). */
export function normalizeTicker(input: string): string {
  return input.trim().toUpperCase();
}
