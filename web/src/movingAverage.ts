import type { ChartCandle } from "./api";

/**
 * Simple moving averages drawn on every price chart.
 * These lengths are chart-only. The scanner's trend score still uses the 10- and 20-day averages.
 */
export const MA_PERIODS = [6, 20, 50] as const;

/** Closes needed before the longest average can be drawn on the first visible candle. */
export const MA_WARMUP = MA_PERIODS[MA_PERIODS.length - 1] - 1;

export const MA_COLORS: Record<(typeof MA_PERIODS)[number], string> = {
  6: "#fbbf24",
  20: "#38bdf8",
  50: "#c084fc",
};

export const CHART_AVERAGES = MA_PERIODS.map((period) => ({ period, color: MA_COLORS[period] }));

/** Tooltip for the moving-average swatches above a price chart. */
export const MA_LEGEND_TITLE = "Simple moving averages of the candles on this chart (6, 20 and 50)";

/** Simple moving average of close, starting once `period` closes exist. */
export function sma(candles: Pick<ChartCandle, "time" | "close">[], period: number): { time: string; value: number }[] {
  if (period < 1) return [];
  const out: { time: string; value: number }[] = [];
  let sum = 0;
  for (let i = 0; i < candles.length; i++) {
    sum += candles[i].close;
    if (i >= period) sum -= candles[i - period].close;
    if (i >= period - 1) out.push({ time: candles[i].time, value: sum / period });
  }
  return out;
}
