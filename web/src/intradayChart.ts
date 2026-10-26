import type { IntradayBar } from "./api";
import { volumeBarColor } from "./macd";

/** EMAs drawn on the 5-minute chart. 360 five-minute bars stand in for a 30-period hourly average. */
export const INTRADAY_EMA_PERIODS = [5, 20, 50, 360] as const;

export type IntradayEmaPeriod = (typeof INTRADAY_EMA_PERIODS)[number];

export const INTRADAY_EMA_COLORS: Record<IntradayEmaPeriod, string> = {
  5: "#f472b6",
  20: "#38bdf8",
  50: "#c084fc",
  360: "#fbbf24",
};

export const INTRADAY_EMAS = INTRADAY_EMA_PERIODS.map((period) => ({
  period,
  color: INTRADAY_EMA_COLORS[period],
}));

/** One regular session fills the chart; the older loaded sessions are a scroll away. */
export const INTRADAY_VISIBLE_BARS = 78;

export const INTRADAY_HEIGHT = 480;

/** Chart time steps 5 minutes per bar so overnight and weekend gaps do not swallow the candles. */
export const INTRADAY_STEP_SEC = 300;

const ET = "America/New_York";

export function intradayLegendTitle(seedSessions: number): string {
  return `Exponential moving averages of regular-session 5-minute closes (5, 20, 50, and 360). The 360 is seeded on ${seedSessions} sessions, several weeks of bars, so it can stand in for a 30-period hourly average.`;
}

export function intradaySessionNote(displaySessions: number): string {
  return `Regular session only (09:30-16:00 ET). Premarket is excluded. ${displaySessions} sessions are loaded; scroll to move through them.`;
}

function formatEt(unix: number, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat("en-US", { timeZone: ET, ...options })
    .format(new Date(unix * 1000))
    .replace(/\u202f|\u00a0/g, " ");
}

/** Crosshair clock, in Eastern Time. */
export function formatIntradayTime(unix: number, withDate: boolean): string {
  const clock = formatEt(unix, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  if (!withDate) return clock;
  const day = formatEt(unix, { month: "short", day: "numeric" });
  return `${day}, ${clock} ET`;
}

/** Axis label when the tick falls on a new day. */
export function formatIntradayDay(unix: number): string {
  return formatEt(unix, { month: "short", day: "numeric" });
}

function emaValue(bar: IntradayBar, period: IntradayEmaPeriod): number | null {
  const value = bar.ema?.[String(period) as `${IntradayEmaPeriod}`];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export interface IntradayPlot {
  candles: { time: number; open: number; high: number; low: number; close: number }[];
  volume: { time: number; value: number; color: string }[];
  lines: { period: IntradayEmaPeriod; color: string; points: { time: number; value: number }[] }[];
  /** Chart time (compressed) to the real unix second, for axis labels. */
  clock: Map<number, number>;
}

/**
 * Candles, volume, and EMA lines for the chart.
 * ``time`` on each point is session-compressed (5 minutes per bar). ``clock`` maps it back
 * to the real bar so the axis still reads Eastern Time across the overnight gap.
 */
export function intradayPlot(bars: readonly IntradayBar[]): IntradayPlot {
  const anchor = bars[0]?.time ?? 0;
  const clock = new Map<number, number>();
  const candles: IntradayPlot["candles"] = [];
  const volume: IntradayPlot["volume"] = [];
  const lines = INTRADAY_EMAS.map((average) => ({
    period: average.period,
    color: average.color,
    points: [] as { time: number; value: number }[],
  }));

  bars.forEach((bar, i) => {
    const time = anchor + i * INTRADAY_STEP_SEC;
    clock.set(time, bar.time);
    candles.push({ time, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
    volume.push({ time, value: bar.volume, color: volumeBarColor(bar.close, bar.open) });
    for (const line of lines) {
      const value = emaValue(bar, line.period);
      if (value != null) line.points.push({ time, value });
    }
  });

  return { candles, volume, lines, clock };
}
