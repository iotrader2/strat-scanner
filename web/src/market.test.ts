import { describe, expect, it } from "vitest";
import { declinersPerAdvancer, marketRead, nasiRead, trendLabel, universeLabel } from "./market";

const row = (symbol: string, mw_green: boolean, full_continuity = false) => ({ symbol, mw_green, full_continuity });

describe("marketRead", () => {
  it("is green when every index has Monthly + Weekly continuity", () => {
    expect(marketRead([row("QQQ", true, true), row("SPY", true), row("IWM", true)])).toEqual({
      tone: "green",
      summary: "3 of 3 indexes have Monthly + Weekly green continuity (1 with full M+W+D)",
    });
  });

  it("is mixed or red otherwise", () => {
    expect(marketRead([row("QQQ", true), row("SPY", false), row("IWM", false)]).tone).toBe("mixed");
    expect(marketRead([row("QQQ", false), row("SPY", false), row("IWM", false)])).toEqual({
      tone: "red",
      summary: "0 of 3 indexes have Monthly + Weekly green continuity",
    });
  });

  it("handles missing data", () => {
    expect(marketRead([]).summary).toBe("No index data yet");
  });
});

describe("trendLabel", () => {
  it("names the three trend calls", () => {
    expect(trendLabel("on").label).toBe("GAME ON!");
    expect(trendLabel("off").label).toBe("DO NOT TRADE");
    expect(trendLabel("caution").label).toBe("CAUTION");
  });
});

describe("nasiRead", () => {
  const points = (values: number[]) => values.map((value, i) => ({ time: `2026-01-${String(i + 1).padStart(2, "0")}`, value }));

  it("calls a falling line under zero a downtrend that has not turned up", () => {
    const read = nasiRead({ value: -743, change: -14, points: points([-700, -710, -720, -730, -740, -743]) });
    expect(read.call).toBe("Downtrend, not turning up");
    expect(read.tone).toBe("bad");
    expect(read.detail).toContain("Below zero");
  });

  it("calls a rising line under zero a downtrend that is turning up", () => {
    const read = nasiRead({ value: -600, change: 20, points: points([-800, -760, -720, -680, -640, -600]) });
    expect(read.call).toBe("Downtrend, but turning up");
  });

  it("calls a rising line above zero an uptrend", () => {
    expect(nasiRead({ value: 200, change: 10, points: points([50, 80, 110, 140, 170, 200]) }).call).toBe("Uptrend");
  });
});

describe("declinersPerAdvancer", () => {
  it("measures how many stocks fell for each one that rose", () => {
    expect(declinersPerAdvancer(1289, 3669)).toBeCloseTo(2.85, 2);
    expect(declinersPerAdvancer(0, 10)).toBeNull();
  });
});

describe("universeLabel", () => {
  it("names the scanner universe the breadth cards are counting", () => {
    expect(universeLabel(645)).toBe("Universe, 645 names");
    expect(universeLabel(2308)).toBe("Universe, 2,308 names");
    expect(universeLabel(1)).toBe("Universe, 1 name");
  });
});
