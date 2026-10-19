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
});
