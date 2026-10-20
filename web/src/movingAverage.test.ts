import { describe, expect, it } from "vitest";
import { sma } from "./movingAverage";

const candles = (closes: number[]) => closes.map((close, i) => ({ time: `2026-01-${String(i + 1).padStart(2, "0")}`, close }));

describe("sma", () => {
  it("starts on the period-th close and averages that window", () => {
    const line = sma(candles([1, 2, 3, 4, 5]), 3);
    expect(line.map((p) => p.value)).toEqual([2, 3, 4]);
    expect(line[0].time).toBe("2026-01-03");
  });

  it("returns nothing until there are enough closes", () => {
    expect(sma(candles([10, 20]), 10)).toEqual([]);
  });

  it("averages a 6-close window", () => {
    // (2+4+6+8+10+12) / 6 = 7, then (4+6+8+10+12+14) / 6 = 9.
    const line = sma(candles([2, 4, 6, 8, 10, 12, 14]), 6);
    expect(line.map((p) => p.value)).toEqual([7, 9]);
    expect(line.map((p) => p.time)).toEqual(["2026-01-06", "2026-01-07"]);
    expect(sma(candles([2, 4, 6, 8, 10]), 6)).toEqual([]);
  });
});
