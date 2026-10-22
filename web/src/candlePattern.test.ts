import { describe, expect, it } from "vitest";
import { CANDLE_PATTERN_LABELS, isCandlePattern, matchesCandlePattern, migrateSetupFilter, type CandlePattern } from "./candlePattern";
import { CANDLE_PATTERN_OPTIONS, HERO_CHIPS, SETUPS_OPTIONS } from "./pages/Scanner";

const bar = (inside = false, hammer = false) => ({ inside, hammer, date: "2026-10-19" });
const row = (W = bar(), D = bar()) => ({ candle_patterns: { W, D } });

const weeklyHammer = row(bar(false, true));
const weeklyInside = row(bar(true));
const dailyHammer = row(bar(), bar(false, true));
const dailyInside = row(bar(), bar(true));
const plain = row();
const missing = { candle_patterns: null };
const rows = [weeklyHammer, weeklyInside, dailyHammer, dailyInside, plain, missing];
const pick = (p: CandlePattern) => rows.filter((r) => matchesCandlePattern(r, p));

describe("Candle Pattern filter", () => {
  it("has exactly Any plus the four patterns", () => {
    expect(CANDLE_PATTERN_OPTIONS.map((o) => o.label)).toEqual(["Any", "Weekly Hammer", "Weekly Inside", "Daily Hammer", "Daily Inside"]);
    expect(CANDLE_PATTERN_LABELS.any).toBe("Any");
  });

  it("matches the pattern on the last completed weekly / daily bar", () => {
    expect(pick("any")).toEqual(rows);
    expect(pick("weekly_hammer")).toEqual([weeklyHammer]);
    expect(pick("weekly_inside")).toEqual([weeklyInside]);
    expect(pick("daily_hammer")).toEqual([dailyHammer]);
    expect(pick("daily_inside")).toEqual([dailyInside]);
  });

  it("carries the old Setup filter's saved value over", () => {
    expect(migrateSetupFilter("inside")).toBe("weekly_inside");
    expect(migrateSetupFilter("hammer")).toBe("weekly_hammer");
    for (const old of ["pending", "triggered", "any", null, "junk"]) expect(migrateSetupFilter(old)).toBe("any");
    expect(isCandlePattern("daily_inside")).toBe(true);
    expect(isCandlePattern("inside")).toBe(false);
  });

  it("leaves the Setups dropdown alone", () => {
    expect(SETUPS_OPTIONS.map((o) => o.value)).toContain("setups_pending");
    expect(SETUPS_OPTIONS.map((o) => o.value)).toContain("setups_triggered");
  });
});

describe("summary tiles", () => {
  it("are in the requested order, with the weekly Strat tiles after", () => {
    expect(HERO_CHIPS.map((c) => c.label)).toEqual([
      "all names",
      "leaders",
      "broken leaders",
      "weekly bullish",
      "weekly bearish",
      "daily bullish",
      "daily bearish",
      "recent breakouts",
      "failed breakouts",
      "awaiting trigger",
      "already triggered",
    ]);
  });
});
