import type { ScanRow } from "./api";

export interface MarketRead {
  tone: "green" | "red" | "mixed";
  summary: string;
}

/** One-line read of the index ETFs: how many have Monthly + Weekly (and full M+W+D) green continuity. */
export function marketRead(rows: Pick<ScanRow, "symbol" | "mw_green" | "full_continuity">[]): MarketRead {
  const n = rows.length;
  const mw = rows.filter((r) => r.mw_green).length;
  const full = rows.filter((r) => r.full_continuity).length;
  const tone = n > 0 && mw === n ? "green" : mw === 0 ? "red" : "mixed";
  const summary =
    n === 0
      ? "No index data yet"
      : `${mw} of ${n} indexes have Monthly + Weekly green continuity` + (full ? ` (${full} with full M+W+D)` : "");
  return { tone, summary };
}
