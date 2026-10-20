import type { ChartCandle } from "./api";

/** MACD settings drawn under every price chart. Fast and slow match the 6- and 20-period chart averages. */
export const MACD_FAST = 6;
export const MACD_SLOW = 20;
export const MACD_SIGNAL = 9;

export const MACD_SETTINGS = { fast: MACD_FAST, slow: MACD_SLOW, signal: MACD_SIGNAL } as const;

export const MACD_LABEL = "MACD (6,20,9)";

/** Price candles (and the volume overlay, when shown) stay on pane 0. MACD is the pane underneath. */
export const PRICE_PANE = 0;
export const MACD_PANE = 1;

/** Share of the chart height given to the MACD pane, relative to the price pane's stretch of 1. */
export const MACD_STRETCH = 0.36;

export const MACD_COLORS = {
  histogramUp: "rgba(34,197,94,0.85)",
  histogramDown: "rgba(244,63,94,0.85)",
} as const;

/** Volume overlay on the price pane. Neutral gray so it is not read as the MACD histogram. */
export const VOLUME_BAR_COLOR = "rgba(148,156,172,0.28)";

export const MACD_TOOLTIP =
  "Histogram only. MACD is EMA 6 minus EMA 20, minus its 9-period signal. Green at or above zero, red below.";

/** First green histogram bar after this many red bars (histogram < 0). */
export const MACD_TRIGGER_MIN_REDS = 3;

export const MACD_TRIGGER_NOTE = "MACD trigger: first green after 3+ red";

/** Up-arrow color for a trigger, on the histogram and under the candle. */
export const MACD_TRIGGER_COLOR = "#22c55e";

export interface MacdTrigger {
  time: string;
  /** Histogram value of the triggering green bar. */
  value: number;
}

export interface MacdPoint {
  time: string;
  macd: number;
  /** Null until the signal EMA has a full seed. */
  signal: number | null;
  /** Null until the signal exists. MACD minus signal. */
  histogram: number | null;
}

/** What the MACD pane draws: the histogram only. The line and signal stay in the math and are not plotted. */
export interface MacdChartSeries {
  label: typeof MACD_LABEL;
  pane: typeof MACD_PANE;
  histogram: { time: string; value: number; color: string }[];
  triggers: MacdTrigger[];
}

/**
 * EMA seeded with the SMA of the first `period` values, then smoothed with k = 2 / (period + 1).
 * Null until that seed exists. This is the same EMA used by standard MACD charts.
 */
export function ema(values: readonly number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period < 1 || values.length < period) return out;
  const k = 2 / (period + 1);
  let prev = 0;
  for (let i = 0; i < period; i++) prev += values[i];
  prev /= period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** Histogram column color: green at or above zero, red below. */
export function histogramColor(value: number): string {
  return value >= 0 ? MACD_COLORS.histogramUp : MACD_COLORS.histogramDown;
}

/**
 * EMA MACD of close. The line starts once both EMAs exist (the slow period).
 * The signal is an EMA of that line, so it starts `signal` MACD values later.
 */
export function macd(
  candles: Pick<ChartCandle, "time" | "close">[],
  fast = MACD_FAST,
  slow = MACD_SLOW,
  signalPeriod = MACD_SIGNAL,
): MacdPoint[] {
  if (fast < 1 || slow < 1 || signalPeriod < 1) return [];
  const closes = candles.map((c) => c.close);
  const fastEma = ema(closes, fast);
  const slowEma = ema(closes, slow);
  const macdValues: number[] = [];
  const macdBars: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    const fastValue = fastEma[i];
    const slowValue = slowEma[i];
    if (fastValue == null || slowValue == null) continue;
    macdValues.push(fastValue - slowValue);
    macdBars.push(i);
  }
  const signalEma = ema(macdValues, signalPeriod);
  return macdBars.map((bar, j) => {
    const signal = signalEma[j];
    return {
      time: candles[bar].time,
      macd: macdValues[j],
      signal,
      histogram: signal == null ? null : macdValues[j] - signal,
    };
  });
}

/**
 * First green bar (histogram >= 0, the same rule as the bar color) after 3 or more red bars.
 * A green that continues the new run does not trigger again. Bars before the histogram exists are skipped.
 */
export function macdTriggers(points: readonly Pick<MacdPoint, "time" | "histogram">[]): MacdTrigger[] {
  const triggers: MacdTrigger[] = [];
  let reds = 0;
  for (const point of points) {
    if (point.histogram == null) continue;
    if (point.histogram >= 0) {
      if (reds >= MACD_TRIGGER_MIN_REDS) triggers.push({ time: point.time, value: point.histogram });
      reds = 0;
    } else {
      reds += 1;
    }
  }
  return triggers;
}

/** Histogram bars for the MACD pane. Null until at least one histogram value exists. */
export function macdChartSeries(candles: Pick<ChartCandle, "time" | "close">[]): MacdChartSeries | null {
  const points = macd(candles);
  const histogram = points
    .filter((p): p is MacdPoint & { histogram: number } => p.histogram != null)
    .map((p) => ({ time: p.time, value: p.histogram, color: histogramColor(p.histogram) }));
  if (histogram.length === 0) return null;
  return { label: MACD_LABEL, pane: MACD_PANE, histogram, triggers: macdTriggers(points) };
}
