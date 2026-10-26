import { describe, expect, it } from "vitest";
import type { IntradayBar } from "./api";
import { VOLUME_DOWN_COLOR, VOLUME_UP_COLOR } from "./macd";
import {
  INTRADAY_EMA_COLORS,
  INTRADAY_EMA_PERIODS,
  INTRADAY_STEP_SEC,
  formatIntradayTime,
  intradayLegendTitle,
  intradayPlot,
  intradaySessionNote,
} from "./intradayChart";

const bar = (time: number, close: number, extra: Partial<IntradayBar> = {}): IntradayBar => ({
  time,
  open: close - 1,
  high: close + 1,
  low: close - 2,
  close,
  volume: 1000,
  ema: {},
  ...extra,
});

describe("5-minute EMA legend", () => {
  it("gives 5, 20, 50, and 360 each their own color", () => {
    expect([...INTRADAY_EMA_PERIODS]).toEqual([5, 20, 50, 360]);
    const colors = INTRADAY_EMA_PERIODS.map((period) => INTRADAY_EMA_COLORS[period]);
    expect(new Set(colors).size).toBe(4);
    expect(intradayLegendTitle(30)).toContain("360");
    expect(intradayLegendTitle(30)).toContain("30 sessions");
    expect(intradaySessionNote(5)).toContain("Premarket is excluded");
    expect(intradaySessionNote(5)).toContain("09:30-16:00 ET");
    expect(intradaySessionNote(5)).toContain("5 sessions");
  });
});

describe("intradayPlot", () => {
  it("compresses the overnight gap and keeps the server EMAs", () => {
    // Friday 15:55 ET and Monday 09:30 ET. The real gap is a weekend; the chart steps 5 minutes.
    const friday = Date.parse("2026-10-23T19:55:00Z") / 1000;
    const monday = Date.parse("2026-10-26T13:30:00Z") / 1000;
    const plot = intradayPlot([
      bar(friday, 10, { close: 10, open: 11, ema: { "5": 1, "20": 2, "50": 3, "360": null } }),
      bar(monday, 12, { ema: { "5": 4, "20": 5, "50": 6, "360": 7.5 } }),
      bar(monday + 300, 9, { open: 12, ema: { "5": 8, "20": 9, "50": 10, "360": 11 } }),
    ]);

    expect(plot.candles.map((c) => c.time)).toEqual([friday, friday + INTRADAY_STEP_SEC, friday + 2 * INTRADAY_STEP_SEC]);
    expect(monday - friday).toBeGreaterThan(60 * 60 * 24);
    expect(plot.clock.get(friday + INTRADAY_STEP_SEC)).toBe(monday);
    expect(plot.volume.map((v) => v.color)).toEqual([VOLUME_DOWN_COLOR, VOLUME_UP_COLOR, VOLUME_DOWN_COLOR]);
    const ema360 = plot.lines.find((line) => line.period === 360);
    expect(ema360?.points.map((point) => point.value)).toEqual([7.5, 11]);
    expect(plot.lines.find((line) => line.period === 5)?.points).toHaveLength(3);
  });
});

describe("Eastern Time labels", () => {
  it("formats the 09:30 ET open", () => {
    const open = Date.parse("2026-10-22T13:30:00Z") / 1000;
    expect(formatIntradayTime(open, false)).toBe("09:30");
    expect(formatIntradayTime(open, true)).toBe("Oct 22, 09:30 ET");
  });
});
