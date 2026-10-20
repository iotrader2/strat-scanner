import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  ema,
  histogramColor,
  macd,
  macdChartSeries,
  macdTriggerMarker,
  macdTriggers,
  MACD_COLORS,
  MACD_TRIGGER_DOWN_COLOR,
  type MacdPoint,
} from "./macd";

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
    expect(series).toEqual({
      label: "MACD (6,20,9)",
      pane: 1,
      histogram: expect.any(Array),
      triggers: macdTriggers(macd(candles(CLOSES))),
    });
    expect(Object.keys(series!)).toEqual(["label", "pane", "histogram", "triggers"]);
    const up = series!.histogram.find((bar) => bar.time === "t27");
    const down = series!.histogram.find((bar) => bar.time === "t34");
    expect(up).toMatchObject({ value: expect.closeTo(0.1299806293, 8), color: MACD_COLORS.histogramUp });
    expect(down).toMatchObject({ value: expect.closeTo(-0.1058761837, 8), color: MACD_COLORS.histogramDown });
  });

  it("returns nothing until the histogram can be drawn", () => {
    expect(macdChartSeries(candles(CLOSES.slice(0, 20)))).toBeNull();
    expect(macdChartSeries(candles(CLOSES.slice(0, 27)))).toBeNull();
    expect(macdChartSeries(candles(CLOSES.slice(0, 28)))?.histogram).toHaveLength(1);
  });
});

const hist = (values: Array<number | null>): MacdPoint[] =>
  values.map((histogram, i) => ({ time: `t${i}`, macd: histogram ?? 0, signal: histogram == null ? null : 0, histogram }));

const up = (time: string, value: number) => ({ time, value, direction: "up" as const });
const down = (time: string, value: number) => ({ time, value, direction: "down" as const });

describe("macd triggers", () => {
  it("triggers on the first green after exactly 3 reds", () => {
    expect(macdTriggers(hist([-1, -1, -1, 0.5]))).toEqual([up("t3", 0.5)]);
    // Zero uses the same rule as the bar color: histogram >= 0 is green.
    expect(macdTriggers(hist([-0.2, -0.4, -0.1, 0]))).toEqual([up("t3", 0)]);
  });

  it("does not trigger after only 2 reds", () => {
    expect(macdTriggers(hist([-1, -1, 0.5]))).toEqual([]);
    expect(macdTriggers(hist([-1, -1, -1, 0.4, -0.2, -0.3, 0.8]))).toEqual([up("t3", 0.4)]);
  });

  it("triggers once at the first green of a long red run", () => {
    const triggers = macdTriggers(hist([-1, -0.5, -0.2, -0.8, -0.3, -0.1, 0.4, 0.9]));
    expect(triggers).toEqual([up("t6", 0.4)]);
  });

  it("does not retrigger while greens continue", () => {
    const triggers = macdTriggers(hist([-1, -1, -1, 0.2, 0.5, 0.1, 1]));
    expect(triggers).toEqual([up("t3", 0.2)]);
  });

  it("does not treat a green at the start of the series as a trigger", () => {
    expect(macdTriggers(hist([0.4]))).toEqual([]);
    expect(macdTriggers(hist([1, 0.2, -1, -1, 0.3]))).toEqual([]);
    expect(macdTriggers(hist([-1, -1, -1]))).toEqual([]);
    // Reds that open the series count. The opening green does not.
    expect(macdTriggers(hist([0.5, -1, -1, -1, 0.2]))).toEqual([up("t4", 0.2)]);
    expect(macdTriggers(hist([null, null, -1, -1, -1, 0.3]))).toEqual([up("t5", 0.3)]);
  });
});

describe("macd bearish triggers", () => {
  it("triggers on the first red after exactly 3 greens", () => {
    expect(macdTriggers(hist([1, 1, 1, -0.5]))).toEqual([down("t3", -0.5)]);
    // Zero is green, so three zeros then a red is the bearish trigger.
    expect(macdTriggers(hist([0, 0, 0, -0.2]))).toEqual([down("t3", -0.2)]);
  });

  it("does not trigger after only 2 greens", () => {
    expect(macdTriggers(hist([1, 1, -0.5]))).toEqual([]);
    expect(macdTriggers(hist([1, 1, 1, -0.4, 0.2, 0.3, -0.8]))).toEqual([down("t3", -0.4)]);
  });

  it("triggers once at the first red of a long green run", () => {
    const triggers = macdTriggers(hist([1, 0.5, 0.2, 0.8, 0.3, 0.1, -0.4, -0.9]));
    expect(triggers).toEqual([down("t6", -0.4)]);
  });

  it("does not retrigger while reds continue", () => {
    const triggers = macdTriggers(hist([1, 1, 1, -0.2, -0.5, -0.1, -1]));
    expect(triggers).toEqual([down("t3", -0.2)]);
  });

  it("does not treat a red at the start of the series as a trigger", () => {
    expect(macdTriggers(hist([-0.4]))).toEqual([]);
    expect(macdTriggers(hist([-1, -0.2, 1, 1, -0.3]))).toEqual([]);
    expect(macdTriggers(hist([1, 1, 1]))).toEqual([]);
    // Greens that open the series count. The opening red does not.
    expect(macdTriggers(hist([-0.5, 1, 1, 1, -0.2]))).toEqual([down("t4", -0.2)]);
    expect(macdTriggers(hist([null, null, 1, 1, 1, -0.3]))).toEqual([down("t5", -0.3)]);
  });

  it("marks both flips in one series and draws the red arrow down from above", () => {
    expect(macdTriggers(hist([-1, -1, -1, 0.4, 0.2, 0.1, -0.3]))).toEqual([up("t3", 0.4), down("t6", -0.3)]);
    expect(macdTriggerMarker({ direction: "up" }, "histogram")).toEqual({
      position: "atPriceBottom",
      shape: "arrowUp",
      color: "#22c55e",
    });
    expect(macdTriggerMarker({ direction: "up" }, "price")).toEqual({
      position: "belowBar",
      shape: "arrowUp",
      color: "#22c55e",
    });
    expect(macdTriggerMarker({ direction: "down" }, "histogram")).toEqual({
      position: "atPriceTop",
      shape: "arrowDown",
      color: MACD_TRIGGER_DOWN_COLOR,
    });
    expect(macdTriggerMarker({ direction: "down" }, "price")).toEqual({
      position: "aboveBar",
      shape: "arrowDown",
      color: MACD_TRIGGER_DOWN_COLOR,
    });
  });
});

describe("macd trigger dates match the backend fixture", () => {
  it("marks the same bars as the Python scanner on the shared close series", () => {
    const path = resolve(dirname(fileURLToPath(import.meta.url)), "../../fixtures/macd_series.json");
    const fixture = JSON.parse(readFileSync(path, "utf8")) as {
      times: string[];
      closes: number[];
      triggers: { time: string; direction: "up" | "down" }[];
    };
    const points = macd(fixture.times.map((time, i) => ({ time, close: fixture.closes[i] })));
    const triggers = macdTriggers(points).map(({ time, direction }) => ({ time, direction }));
    expect(triggers).toEqual(fixture.triggers);
  });
});
