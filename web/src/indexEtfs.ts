/** The three index ETFs (QQQ, SPY, IWM): the backend's "benchmark" group, also shown on State of the Market. */

export const INDEX_ETFS = ["QQQ", "SPY", "IWM"] as const;

type Row = { symbol: string; kind: string; indexes?: string };

/** True for the QQQ / SPY / IWM rows (tagged "benchmark" by the backend; the symbols are the fallback). */
export function isIndexEtf(r: Row): boolean {
  return r.kind === "etf" && (r.indexes === "benchmark" || (INDEX_ETFS as readonly string[]).includes(r.symbol));
}

/**
 * The ETFs view lists the index ETFs as reference rows (they are rarely ETF leaders, so Leaders would hide them).
 * Not under a single-setup option (`setupView`): there a row is only listed when it has that setup, otherwise
 * QQQ / SPY / IWM would appear in, say, Delayed High Volume Close with no setup at all. The other filters
 * (search, theme, liquidity, ATR) still apply.
 */
export function keepIndexEtf(r: Row, kind: string, setupView = false): boolean {
  return kind === "etf" && !setupView && isIndexEtf(r);
}
