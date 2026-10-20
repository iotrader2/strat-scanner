import { describe, expect, it } from "vitest";
import { ema, histogramColor, macd, macdChartSeries, MACD_COLORS } from "./macd";

const candles = (closes: number[]) => closes.map((close, i) => ({ time: `t${String(i).padStart(2, "0")}`, close }));

/**
 * Uneven closes used as the known MACD(6,20,9) series.
 * Expected values were computed independently (SMA-seeded EMA, k = 2 / (period + 1)).
 */
const CLOSES = [
  10, 10.5, 11, 10.8, 10.2, 10.6, 11.4, 12, 11.7, 11.1, 11.5, 12.2, 12.8, 12.4, 11.9, 12.6, 13.1, 13.5, 13.0, 12.7, 13.2,
  13.8, 14.4, 14.0, 13.6, 14.1, 14.7, 15.2, 14.8, 14.3, 14.9, 15.5, 16.0, 15.4, 15.0,
];

describe("ema", () => {
  it("seeds with the SMA and then applies k = 2 / (period + 1)", () => {
    // period 3, k = 0.5. SMA(1, 2, 3) = 2. Next: 4 * 0.5 + 2 * 0.5 = 3. Next: 6 * 0.5 + 3 * 0.5 = 4.5.
    expect(ema([1, 2, 3, 4, 6], 3)).toEqual([null, null, 2, 3, 4.5]);
  });
});

describe("macd 6, 20, 9", () => {
  const points = macd(candles(CLOSES));

  it("starts the MACD line on the slow-period bar and the signal nine MACD values later", () => {
    expect(points).toHaveLength(CLOSES.length - 20 + 1);
    expect(points[0].time).toBe("t19");
    expect(points[0].signal).toBeNull();
    expect(points[0].histogram).toBeNull();
    // EMA(20) on bar 19 is still its SMA seed: the mean of the first 20 closes.
    const ema20Seed = CLOSES.slice(0, 20).reduce((sum, v) => sum + v, 0) / 20;
    expect(ema20Seed).toBeCloseTo(11.75, 10);
    expect(points[0].macd).toBeCloseTo(1.0338920985, 8);
    expect(points[7].signal).toBeNull();
    expect(points[8].time).toBe("t27");
    expect(points[8].signal).toBeCloseTo(1.1195305313, 8);
    expect(points[8].histogram).toBeCloseTo(0.1299806293, 8);
  });

  it("matches the known line, signal and histogram on the last bars", () => {
    const last = points[points.length - 1];
    expect(last.time).toBe("t34");
    expect(last.macd).toBeCloseTo(1.0105497045, 8);
    expect(last.signal).toBeCloseTo(1.1164258882, 8);
    expect(last.histogram).toBeCloseTo(-0.1058761837, 8);
    expect(last.histogram).toBeCloseTo(last.macd - (last.signal ?? 0), 10);

    const earlier = points[points.length - 6];
    expect(earlier.macd).toBeCloseTo(1.0607624075, 8);
    expect(earlier.signal).toBeCloseTo(1.122692784, 8);
    expect(earlier.histogram).toBeCloseTo(-0.0619303765, 8);
  });

  it("is zero when every close is the same", () => {
    const flat = macd(candles(Array.from({ length: 40 }, () => 10)));
    expect(flat.length).toBeGreaterThan(0);
    for (const point of flat) {
      expect(point.macd).toBeCloseTo(0, 10);
      if (point.signal != null) expect(point.signal).toBeCloseTo(0, 10);
      if (point.histogram != null) expect(point.histogram).toBeCloseTo(0, 10);
    }
  });
});

describe("macd chart series", () => {
  it("colors the histogram up at or above zero and down below it", () => {
    expect(histogramColor(0)).toBe(MACD_COLORS.histogramUp);
    expect(histogramColor(0.13)).toBe(MACD_COLORS.histogramUp);
    expect(histogramColor(-0.06)).toBe(MACD_COLORS.histogramDown);

    const series = macdChartSeries(candles(CLOSES));
    expect(series).not.toBeNull();
    const up = series!.histogram.find((bar) => bar.time === "t27");
    const down = series!.histogram.find((bar) => bar.time === "t34");
    expect(up).toMatchObject({ value: expect.closeTo(0.1299806293, 8), color: MACD_COLORS.histogramUp });
    expect(down).toMatchObject({ value: expect.closeTo(-0.1058761837, 8), color: MACD_COLORS.histogramDown });
  });

  it("returns nothing until the MACD line can be drawn", () => {
    expect(macdChartSeries(candles(CLOSES.slice(0, 20)))).toBeNull();
  });
});
