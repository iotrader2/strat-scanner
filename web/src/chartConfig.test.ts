import { describe, expect, it } from "vitest";
import {
  MACD_COLORS,
  MACD_LABEL,
  MACD_PANE,
  MACD_SETTINGS,
  MACD_STRETCH,
  MACD_TRIGGER_MIN_REDS,
  MACD_TRIGGER_NOTE,
  PRICE_PANE,
  VOLUME_BAR_COLOR,
} from "./macd";
import { CHART_AVERAGES, MA_COLORS, MA_LEGEND_TITLE, MA_PERIODS } from "./movingAverage";

describe("price chart overlays", () => {
  it("draws 6, 20 and 50 period averages and not the old 10", () => {
    const periods: number[] = [...MA_PERIODS];
    expect(periods).toEqual([6, 20, 50]);
    expect(periods).not.toContain(10);
    expect(CHART_AVERAGES).toEqual([
      { period: 6, color: "#fbbf24" },
      { period: 20, color: "#38bdf8" },
      { period: 50, color: "#c084fc" },
    ]);
    expect(MA_COLORS[6]).toBe("#fbbf24");
    expect(MA_COLORS[20]).toBe("#38bdf8");
    expect(MA_COLORS[50]).toBe("#c084fc");
    expect(MA_LEGEND_TITLE).toContain("6, 20 and 50");
  });
});

describe("MACD pane", () => {
  it("uses fast 6, slow 20, signal 9 and draws only the histogram under the price chart", () => {
    expect(MACD_SETTINGS).toEqual({ fast: 6, slow: 20, signal: 9 });
    expect(MACD_LABEL).toBe("MACD (6,20,9)");
    expect(PRICE_PANE).toBe(0);
    expect(MACD_PANE).toBe(1);
    expect(MACD_STRETCH).toBeGreaterThan(0);
    expect(MACD_STRETCH).toBeLessThan(1);
    expect(MACD_COLORS.histogramUp).not.toBe(MACD_COLORS.histogramDown);
    expect(Object.keys(MACD_COLORS)).toEqual(["histogramUp", "histogramDown"]);
    expect(VOLUME_BAR_COLOR).not.toBe(MACD_COLORS.histogramUp);
    expect(VOLUME_BAR_COLOR).not.toBe(MACD_COLORS.histogramDown);
    expect(VOLUME_BAR_COLOR).not.toMatch(/34,\s*197,\s*94|244,\s*63,\s*94/);
    expect(MACD_TRIGGER_MIN_REDS).toBe(3);
    expect(MACD_TRIGGER_NOTE).toBe("MACD trigger: first green after 3+ red");
  });
});
