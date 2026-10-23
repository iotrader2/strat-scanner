import type { DayRange, Ema5m, EmaSide, ListIntraday, PremarketPrint } from "./api";
import { formatLocal } from "./live";

/** 1234567 -> "1.2M", 135167 -> "135K". */
export function fmtVolume(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}K`;
  return String(Math.round(v));
}

const SOURCE: Record<string, string> = {
  iex: "IEX trade, real time",
  "delayed sip": "all-exchange trade, 15 min delayed",
  "sip bar": "all-exchange 5-min bar, 15 min delayed",
};

export function premarketTitle(pm: PremarketPrint): string {
  const head = pm.final ? "Premarket close" : "Premarket last";
  const src = SOURCE[pm.source] ?? pm.source;
  const parts = [
    `${head} ${pm.price.toFixed(2)} (${src}, ${formatLocal(pm.time)}) vs prior close ${pm.prev_close.toFixed(2)}`,
  ];
  if (pm.volume !== null) {
    const through = pm.volume_through ? ` through ${formatLocal(pm.volume_through)}` : "";
    parts.push(`premarket volume ${Math.round(pm.volume).toLocaleString()}${through}`);
  }
  return parts.join(" · ");
}

const BASIS: Record<Ema5m["basis"], string> = {
  live: "last 5-min close",
  premarket: "premarket print",
  close: "last regular close",
};

/** Pill for one EMA: "Above" / "Below" (green / red), "At" neutral. */
export function emaSide(em: Ema5m, period: 6 | 20): { side: EmaSide; label: string; title: string } {
  const side = period === 6 ? em.vs6 : em.vs20;
  const value = period === 6 ? em.ema6 : em.ema20;
  const label = side === "above" ? "Above" : side === "below" ? "Below" : "At";
  const title = `${BASIS[em.basis]} ${em.price.toFixed(2)} vs ${period} EMA ${value.toFixed(2)} on the 5-minute chart (regular-session bars, through ${formatLocal(em.bar_time)})`;
  return { side, label, title };
}

/** Distance from the EMA in percent, for sorting. */
export function emaDistance(em: Ema5m | null | undefined, period: 6 | 20): number | null {
  if (!em) return null;
  const value = period === 6 ? em.ema6 : em.ema20;
  return value > 0 ? (em.price / value - 1) * 100 : null;
}

/** Tone for the day-range marker: green in the top 30% of the range, red in the bottom 30%. */
export function rangeTone(pct: number): "near-high" | "near-low" | "mid" {
  if (pct >= 70) return "near-high";
  if (pct <= 30) return "near-low";
  return "mid";
}

const RANGE_BASIS: Record<DayRange["basis"], string> = {
  regular: "Today's range",
  premarket: "Premarket range so far",
  "last session": "Last session's range",
};

export function rangeTitle(r: DayRange): string {
  return `${RANGE_BASIS[r.basis]} (${r.session}): low ${r.low.toFixed(2)} · high ${r.high.toFixed(2)} · last ${r.last.toFixed(2)} · ${Math.round(r.pct)}% of the range`;
}

/** Row highlight while the last completed 5-min bar is a close back above the 6 and/or 20 EMA. */
export function crossHighlight(info: ListIntraday | null | undefined): { className: string; title: string } | null {
  const em = info?.ema5m;
  if (!em || em.highlight.length === 0) return null;
  const which = em.highlight.map((n) => `${n} EMA`).join(" and ");
  const bar = em.highlight_bar ? ` on the ${formatLocal(em.highlight_bar)} bar` : "";
  const until = em.highlight_until ? ` Clears at ${formatLocal(em.highlight_until)} when the next bar completes.` : "";
  return {
    className: "ema-cross",
    title: `Crossed back above the ${which} (5m)${bar}: the last completed bar closed above it after the prior bar closed at or below it.${until}`,
  };
}
