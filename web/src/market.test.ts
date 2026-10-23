import { describe, expect, it } from "vitest";
import {
  declinersPerAdvancer,
  MARKET_SCORE_MESSAGES,
  maChip,
  marketRead,
  marketScoreRead,
  nasiRead,
  sessionBadge,
  trendLabel,
  universeLabel,
} from "./market";

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

describe("sessionBadge", () => {
  it("names the extended session and stays off once the regular session is back", () => {
    expect(sessionBadge("premarket")).toEqual({
      label: "Premarket",
      title: "Change versus the prior regular-session close",
    });
    expect(sessionBadge("after_hours")?.label).toBe("After hours");
    expect(sessionBadge(null)).toBeNull();
    expect(sessionBadge(undefined)).toBeNull();
  });
});

describe("universeLabel", () => {
  it("names the scanner universe the breadth cards are counting", () => {
    expect(universeLabel(645)).toBe("Universe, 645 names");
    expect(universeLabel(2308)).toBe("Universe, 2,308 names");
    expect(universeLabel(1)).toBe("Universe, 1 name");
  });
});

describe("marketScoreRead", () => {
  it("maps every score 0–9 to its message, red to green", () => {
    const reads = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => marketScoreRead(n));
    expect(MARKET_SCORE_MESSAGES).toHaveLength(10);
    expect(reads.map((r) => r.message)).toEqual(MARKET_SCORE_MESSAGES);
    expect(reads.map((r) => `${r.score}/${r.max}`)).toEqual(["0/9", "1/9", "2/9", "3/9", "4/9", "5/9", "6/9", "7/9", "8/9", "9/9"]);
    expect(reads[0].message).toBe("Market is screwed. DO NOT TRADE. Close the laptop and go touch grass.");
    expect(reads[1].message).toBe("Barely a pulse. Cash is a position, and today it's the best one.");
    expect(reads[2].message).toBe("Clown market. Every breakout is a trap with a bow on it.");
    expect(reads[6].message).toBe("Sun's peeking out. Starter positions on the best setups.");
    expect(reads[8].message).toBe("One straggler left. Press the leaders, keep your stops tight.");
    expect(reads[9].message).toBe("GAME ON. All engines firing. Size up on A+ setups and trust your stops.");
    expect(reads[0].hue).toBe(0);
    expect(reads[9].hue).toBe(120);
    const hues = reads.map((r) => r.hue);
    expect(hues).toEqual([...hues].sort((a, b) => a - b));
    expect(new Set(hues).size).toBe(10);
  });

  it("clamps odd values to 0–9", () => {
    expect(marketScoreRead(-3).score).toBe(0);
    expect(marketScoreRead(12).score).toBe(9);
    expect(marketScoreRead(4.6).score).toBe(5);
    expect(marketScoreRead(Number.NaN).message).toBe(MARKET_SCORE_MESSAGES[0]);
  });
});

describe("maChip", () => {
  it("is green above an average and red below or on it", () => {
    expect(maChip({ period: 6, value: 100, above: true })).toEqual({ className: "above", title: "Price above the 6-day simple average (100.00)" });
    expect(maChip({ period: 50, value: 726.68, above: false })).toEqual({ className: "below", title: "Price below the 50-day simple average (726.68)" });
  });
});
