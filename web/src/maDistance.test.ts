import { describe, expect, it } from "vitest";
import { fmtMaDistance, maDistance, maDistanceTone, maLabel, maTitle, MA_DISTANCE_PERIODS } from "./maDistance";

describe("price distance from the 6 / 20 / 50 SMA", () => {
  it("formats signed with one decimal and a percent sign, 0.0% on the average, em dash when missing", () => {
    expect(fmtMaDistance(3)).toBe("+3.0%");
    expect(fmtMaDistance(-0.2)).toBe("-0.2%");
    expect(fmtMaDistance(0)).toBe("0.0%");
    expect(fmtMaDistance(0.04)).toBe("0.0%");
    expect(fmtMaDistance(-0.04)).toBe("0.0%");
    expect(fmtMaDistance(2.42)).toBe("+2.4%");
    expect(fmtMaDistance(-12.345)).toBe("-12.3%");
    expect(fmtMaDistance(null)).toBe("—");
  });

  it("is green above, red below, neutral at 0.0% or missing", () => {
    expect(maDistanceTone(0.3)).toBe("green-text");
    expect(maDistanceTone(-0.2)).toBe("red-text");
    expect(maDistanceTone(0.04)).toBe("muted");
    expect(maDistanceTone(null)).toBe("muted");
  });

  it("reads the row's backend values and treats missing data as null", () => {
    expect(MA_DISTANCE_PERIODS).toEqual([6, 20, 50]);
    const row = { ma_dist_pct: { "6": 1.2, "20": -0.4, "50": null } };
    expect(maDistance(row, 6)).toBe(1.2);
    expect(maDistance(row, 20)).toBe(-0.4);
    expect(maDistance(row, 50)).toBeNull();
    expect(maDistance({ ma_dist_pct: undefined }, 6)).toBeNull();
    expect(maDistance({ ma_dist_pct: null }, 20)).toBeNull();
  });

  it("labels", () => {
    expect(maLabel(20)).toBe("vs 20 MA");
    expect(maTitle(6)).toBe("Percent distance of price from the daily 6 SMA; 0% = on the average");
  });
});
