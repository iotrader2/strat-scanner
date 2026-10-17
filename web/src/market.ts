import type { Nasi, ScanRow, TrendCall } from "./api";

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

export interface TrendLabel {
  label: string;
  detail: string;
}

/** Banner copy for the 10/20/50-day trend call. */
export function trendLabel(call: TrendCall): TrendLabel {
  if (call === "on") {
    return { label: "GAME ON!", detail: "QQQ, SPY and IWM are above their 10, 20 and 50 day averages." };
  }
  if (call === "off") {
    return { label: "DO NOT TRADE", detail: "QQQ, SPY and IWM are below their 10, 20 and 50 day averages." };
  }
  return { label: "CAUTION", detail: "The indexes are split around their 10, 20 and 50 day averages." };
}

export interface NasiRead {
  tone: "bad" | "warn" | "good";
  call: string;
  detail: string;
}

const NASI_MEANING = "$NASI is the running total of Nasdaq stocks rising minus stocks falling.";

/** Below zero is a breadth downtrend. Turning up means the line is higher than it was a week ago. */
export function nasiRead(nasi: Pick<Nasi, "value" | "change" | "points">): NasiRead {
  const prior = nasi.points.length >= 6 ? nasi.points[nasi.points.length - 6].value : null;
  const week = prior === null ? nasi.change : nasi.value - prior;
  const rising = week !== null && week > 0;
  const below = nasi.value < 0;
  if (below && !rising) {
    return {
      tone: "bad",
      call: "Downtrend, not turning up",
      detail: `${NASI_MEANING} Below zero is a downtrend, and the line is still falling.`,
    };
  }
  if (below && rising) {
    return {
      tone: "warn",
      call: "Downtrend, but turning up",
      detail: `${NASI_MEANING} It is still below zero, but the line has started to rise.`,
    };
  }
  if (!below && rising) {
    return {
      tone: "good",
      call: "Uptrend",
      detail: `${NASI_MEANING} Above zero means more stocks are rising than falling, and the line is still climbing.`,
    };
  }
  return {
    tone: "warn",
    call: "Above zero, rolling over",
    detail: `${NASI_MEANING} Breadth is still positive, but the line is no longer rising.`,
  };
}

/** Declining issues divided by advancing issues, when both sides traded. */
export function declinersPerAdvancer(advancing: number, declining: number): number | null {
  if (advancing <= 0 || declining < 0) return null;
  return declining / advancing;
}
