import type { ScanRow } from "./api";

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

/** Trimmed, upper-cased ticker as typed into the Add symbol box ("" when blank). */
export function normalizeTicker(input: string): string {
  return input.trim().toUpperCase();
}
