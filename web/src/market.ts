import type { Nasi, ScanRow, TrendCall } from "./api";

export type IndexSession = "premarket" | "after_hours";

/** Label for the index-card badge, or null during the regular session and when the market is closed. */
export function sessionBadge(session: IndexSession | null | undefined): { label: string; title: string } | null {
  if (session === "premarket") {
    return { label: "Premarket", title: "Change versus the prior regular-session close" };
  }
  if (session === "after_hours") {
    return { label: "After hours", title: "Change versus today's regular-session close" };
  }
  return null;
}

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

/** Banner copy for the 6/20/50-day trend call. */
export function trendLabel(call: TrendCall): TrendLabel {
  if (call === "on") {
    return { label: "GAME ON!", detail: "QQQ, SPY and IWM are above their 6, 20 and 50 day averages." };
  }
  if (call === "off") {
    return { label: "DO NOT TRADE", detail: "QQQ, SPY and IWM are below their 6, 20 and 50 day averages." };
  }
  return { label: "CAUTION", detail: "The indexes are split around their 6, 20 and 50 day averages." };
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

/** Subtitle for a breadth card. ``names`` is how many symbols the scanner counted. */
export function universeLabel(names: number): string {
  const n = Math.max(0, Math.round(names));
  return `Universe, ${n.toLocaleString("en-US")} ${n === 1 ? "name" : "names"}`;
}

/** Banner copy for the market score (0–9), from worst to best. */
export const MARKET_SCORE_MESSAGES: readonly string[] = [
  "🚨 Market is screwed. DO NOT TRADE. Close the laptop and go touch grass.",
  "⚰️ Barely a pulse. Cash is a position, and today it's the best one.",
  "🤡 Clown market. Every breakout is a trap with a bow on it.",
  "🫠 Choppy slop. The market is a blender and your account is the smoothie.",
  "🤷 Coin flip market. Half size, A+ setups only, no revenge trades.",
  "👀 Getting interesting. Leaders are stretching, start loading the watchlist.",
  "🌤️ Sun's peeking out. Starter positions on the best setups.",
  "🚀 Almost there. Green light for A+ setups, don't chase.",
  "💪 One straggler left. Press the leaders, keep your stops tight.",
  "🔥 GAME ON. All engines firing. Size up on A+ setups and trust your stops.",
];

export const MARKET_SCORE_MAX = MARKET_SCORE_MESSAGES.length - 1;

export interface MarketScoreRead {
  score: number;
  max: number;
  message: string;
  /** Red (0) to green (9), as an HSL hue. */
  hue: number;
}

/** Message and color for a 0–9 market score. Out-of-range, fractional or missing scores are clamped and rounded. */
export function marketScoreRead(score: number): MarketScoreRead {
  const top = MARKET_SCORE_MAX;
  const level = Math.min(top, Math.max(0, Math.round(Number.isFinite(score) ? score : 0)));
  return { score: level, max: top, message: MARKET_SCORE_MESSAGES[level], hue: Math.round((level / top) * 120) };
}

export interface MaChip {
  className: "above" | "below";
  title: string;
}

/** A 6/20/50 chip on the trend banner: green when the price is above the average, red otherwise (on it counts as below). */
export function maChip(avg: { period: number; value: number; above: boolean }): MaChip {
  return {
    className: avg.above ? "above" : "below",
    title: `Price ${avg.above ? "above" : "below"} the ${avg.period}-day simple average (${avg.value.toFixed(2)})`,
  };
}
