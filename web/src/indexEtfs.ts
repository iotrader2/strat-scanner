/** The three index ETFs (QQQ, SPY, IWM): the backend's "benchmark" group, also shown on State of the Market. */

export const INDEX_ETFS = ["QQQ", "SPY", "IWM"] as const;

type Row = { symbol: string; kind: string; indexes?: string };

/** True for the QQQ / SPY / IWM rows (tagged "benchmark" by the backend; the symbols are the fallback). */
export function isIndexEtf(r: Row): boolean {
  return r.kind === "etf" && (r.indexes === "benchmark" || (INDEX_ETFS as readonly string[]).includes(r.symbol));
}

/**
 * The ETFs view always lists the index ETFs as reference rows, whatever the Setups option (they are rarely
 * ETF leaders, so Leaders would hide them). The other filters (search, theme, setup, liquidity, ATR) still apply.
 */
export function keepIndexEtf(r: Row, kind: "all" | "stock" | "etf"): boolean {
  return kind === "etf" && isIndexEtf(r);
}
