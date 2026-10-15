import { describe, expect, it } from "vitest";
import {
  SLIDER_STEPS,
  fmtCompact,
  niceRound,
  passesLiquidity,
  sliderToValue,
  sliderValue,
  syncSliderPosition,
  valueToSlider,
} from "./logScale";

const MIN = 100_000;
const MAX = 50_000_000;

describe("log-scale slider", () => {
  it("maps the ends of the slider to min and max", () => {
    expect(sliderToValue(0, MIN, MAX)).toBeCloseTo(MIN);
    expect(sliderToValue(SLIDER_STEPS, MIN, MAX)).toBeCloseTo(MAX);
  });

  it("puts the geometric mean in the middle", () => {
    expect(sliderToValue(SLIDER_STEPS / 2, MIN, MAX)).toBeCloseTo(Math.sqrt(MIN * MAX), 0);
  });

  it("round-trips values", () => {
    for (const v of [100_000, 250_000, 1_000_000, 2_500_000, 50_000_000]) {
      expect(sliderToValue(valueToSlider(v, MIN, MAX), MIN, MAX) / v).toBeCloseTo(1, 2);
    }
  });

  it("clamps out-of-range inputs", () => {
    expect(valueToSlider(1, MIN, MAX)).toBe(0);
    expect(valueToSlider(1e12, MIN, MAX)).toBe(SLIDER_STEPS);
    expect(sliderToValue(-5, MIN, MAX)).toBeCloseTo(MIN);
  });

  it("is monotonic", () => {
    let prev = 0;
    for (let p = 0; p <= SLIDER_STEPS; p += 50) {
      const v = sliderToValue(p, MIN, MAX);
      expect(v).toBeGreaterThan(prev);
      prev = v;
    }
  });
});

describe("formatting", () => {
  it("formats compact share counts", () => {
    expect(fmtCompact(2_500_000)).toBe("2.5M");
    expect(fmtCompact(100_000)).toBe("100K");
    expect(fmtCompact(50_000_000)).toBe("50M");
    expect(fmtCompact(12_340_000)).toBe("12.3M");
    expect(fmtCompact(1_200_000_000)).toBe("1.2B");
    expect(fmtCompact(950)).toBe("950");
  });

  it("rounds to two significant digits", () => {
    expect(niceRound(2_487_312)).toBe(2_500_000);
    expect(niceRound(143_900)).toBe(140_000);
    expect(niceRound(50_000_000)).toBe(50_000_000);
  });
});

describe("passesLiquidity", () => {
  const row = { price: 50, avg_dollar_volume: 120e6, avg_volume: 2.4e6 };
  it("applies all three thresholds", () => {
    expect(passesLiquidity(row, { minPrice: 10, minDollarVolume: 50e6, minAvgVolume: 1e6 })).toBe(true);
    expect(passesLiquidity(row, { minPrice: 10, minDollarVolume: 50e6, minAvgVolume: 2.5e6 })).toBe(false);
    expect(passesLiquidity(row, { minPrice: 10, minDollarVolume: 200e6, minAvgVolume: 1e5 })).toBe(false);
    expect(passesLiquidity(row, { minPrice: 60, minDollarVolume: 0, minAvgVolume: 0 })).toBe(false);
  });
});

describe("slider stepping", () => {
  it("advances one keyboard step at a time from the minimum without snapping back", () => {
    let value = MIN;
    let pos = valueToSlider(value, MIN, MAX);
    const seen: number[] = [];
    for (let i = 0; i < 400; i++) {
      pos = syncSliderPosition(value, MIN, MAX, pos) + 1;
      value = sliderValue(pos, MIN, MAX);
      seen.push(value);
    }
    expect(pos).toBe(400);
    expect(value).toBeGreaterThan(1_000_000);
    for (let i = 1; i < seen.length; i++) expect(seen[i]).toBeGreaterThanOrEqual(seen[i - 1]);
  });

  it("resyncs when the value changes from outside", () => {
    expect(syncSliderPosition(2_500_000, MIN, MAX, 3)).toBe(valueToSlider(2_500_000, MIN, MAX));
  });
});
