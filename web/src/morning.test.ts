import { describe, expect, it } from "vitest";
import {
  bestSentence,
  displayTime,
  orderedRows,
  outcomeLine,
  returnTone,
  shownRank,
  realizedR,
  signedPct,
  signedR,
  type MorningRow,
} from "./morning";

const row = (rank: number, symbol: string, at?: number): MorningRow => ({
  rank,
  symbol,
  name: symbol,
  score: 80 - rank,
  rs: 0.95,
  as_of: "2026-10-15",
  windows: at == null ? {} : { "10:15": { rank: at, d3_ret: at === 1 ? 2.5 : -0.4, eod_ret: 0.2, stopped: 0, stop_day: null } },
});

describe("morning check-in view", () => {
  it("shows the clock without a leading zero", () => {
    expect(displayTime("09:45")).toBe("9:45");
    expect(displayTime("10:00")).toBe("10:00");
  });

  it("orders the prior-close list by leadership rank and a check-in by its own rank", () => {
    const rows = [row(1, "AAA", 2), row(2, "BBB", 1)];
    expect(orderedRows(rows, "leaders").map((r) => r.symbol)).toEqual(["AAA", "BBB"]);
    expect(orderedRows(rows, "10:15").map((r) => r.symbol)).toEqual(["BBB", "AAA"]);
    expect(shownRank(rows[1], "10:15")).toBe(1);
    expect(shownRank(rows[0], "leaders")).toBe(1);
    const waiting = row(1, "CCC");
    waiting.windows["10:15"] = { rank: null, qualified: 0, d3_ret: 9 };
    expect(orderedRows([waiting, rows[0]], "10:15").map((r) => r.symbol)).toEqual(["AAA", "CCC"]);
    expect(shownRank(waiting, "10:15")).toBeNull();
  });

  it("colors returns and writes a hover line without lookahead language", () => {
    expect(returnTone(1.2)).toBe("up");
    expect(returnTone(-0.1)).toBe("down");
    expect(returnTone(null)).toBe("flat");
    expect(signedPct(1.25)).toBe("+1.3%");
    expect(signedPct(-0.04, 2)).toBe("-0.04%");
    expect(signedPct(-0.02)).toBe("0.0%");
    expect(signedR(3)).toBe("+3.0R");
    expect(signedR(-1)).toBe("-1.0R");
    expect(realizedR({ stopped: 1, stop_day: 0, stop_ret: -1, d3_ret: 4 }, "d3_ret")).toBe(-1);
    expect(realizedR({ stopped: 1, stop_day: 2, stop_ret: -1, eod_ret: 1.5, d3_ret: 4 }, "eod_ret")).toBe(1.5);
    expect(outcomeLine({ eod_ret: 1, d1_ret: null, d3_ret: 2, d5_ret: null, stopped: 1, stop_day: 0, stop_ret: -1.5 })).toContain(
      "stopped same day",
    );
    expect(outcomeLine(undefined)).toBe("No print at this time");
    expect(outcomeLine({ qualified: 0 })).toBe("Has not closed above the 20 RMA");
  });

  it("states the best check-in from the close-to-close hold", () => {
    const text = bestSentence({
      window: "10:15",
      horizon: "d3",
      expectancy: 0.42,
      win_rate: 0.56,
      avg: 0.5,
      median: 0.3,
      stop_hit_rate: 0.3,
      n_days: 40,
      n_trades: 400,
      vs_qqq: 0.2,
    });
    expect(text).toContain("10:15");
    expect(text).toContain("+0.50R");
    expect(text).toContain("56%");
    expect(text).toContain("30%");
    expect(text).toContain("20 RMA");
    expect(text).toContain("1% stop");
    expect(bestSentence(null)).toBeNull();
  });
});
