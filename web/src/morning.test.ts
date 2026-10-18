import { describe, expect, it } from "vitest";
import {
  bestSentence,
  crossNote,
  crossSentence,
  reclaimNote,
  reclaimSentence,
  displayTime,
  entryNote,
  stratNote,
  stratSentence,
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

  it("notes the EMA book's average entry time and stop distance", () => {
    expect(
      entryNote({
        id: "ema_all",
        label: "EMA all",
        rule: "ema",
        n_fills: 4,
        avg_entry: "10:22",
        median_entry: "9:45",
        avg_stop_pct: 0.82,
        horizons: {},
      }),
    ).toBe("EMA all enters at 10:22 on average (median 9:45). The stop averages 0.82% under the entry.");
  });

  it("describes a Strat book and compares the day-3 winner with the 10:30 first book", () => {
    const book = {
      id: "15_all",
      label: "All",
      title: "15-minute all",
      timeframe: 15,
      n_fills: 4,
      avg_entry: "10:40",
      median_entry: "10:15",
      avg_stop_pct: 1.25,
      pattern_counts: { "2d-2u": 2, "2d-1-2u": 1, "3-1-2u": 1, "1-2d-2u": 0 },
      finished_2u_rate: 0.5,
      horizons: {},
    };
    expect(stratNote(book)).toBe(
      "All enters at 10:40 on average (median 10:15). The stop averages 1.25% under the entry. 2d-2u 2, 2d-1-2u 1, 3-1-2u 1, 1-2d-2u 0. Finished as 2U: 50%.",
    );
    expect(
      stratSentence({
        books: {},
        order: [],
        panels: [],
        definition: "",
        best: { id: "15_rma_first", label: "15-minute RMA first", avg_r: 0.12, n_days: 40, n_trades: 40, vs_rma_first: -0.17 },
        benchmark: { label: "10:30 first", avg_r: 0.29, n_days: 58, n_trades: 58 },
      }),
    ).toBe("15-minute RMA first is the best of these books by day 3 at +0.12R per morning. The 10:30 first-name RMA book is +0.29R by day 3. Paired against that book it is -0.17R.");
    expect(stratSentence(undefined)).toBeNull();
  });

  it("counts names that opened above the average and compares the cross books with the 10:30 first book", () => {
    expect(
      crossNote({
        id: "rma",
        label: "RMA",
        rule: "rma",
        n_fills: 40,
        avg_entry: "10:05",
        median_entry: "9:45",
        avg_stop_pct: 0.64,
        opened_above: 12,
        opened_above_rate: 0.3,
        trades_per_day: 6.7,
        tape_days: 60,
        horizons: {},
      }),
    ).toBe(
      "RMA enters at 10:05 on average (median 9:45). The stop averages 0.64% under the entry. 12 of 40 opened above the average. 6.7 trades per day.",
    );
    expect(
      crossSentence({
        books: {},
        order: [],
        definition: "",
        best: { id: "sma", label: "SMA", avg_r: -0.11, n_days: 58, n_trades: 400, vs_rma_first: -0.4 },
        benchmark: { label: "10:30 first", avg_r: 0.29, n_days: 58, n_trades: 58 },
      }),
    ).toBe("SMA is the best of these books by day 3 at -0.11R per morning. The 10:30 first-name RMA book is +0.29R by day 3. Paired against that book it is -0.40R.");
    expect(crossSentence(undefined)).toBeNull();
  });

  it("notes an EMA pullback reclaim and compares the day-3 winner with the 10:30 first book", () => {
    expect(
      reclaimNote({
        id: "pullback_all",
        label: "All",
        title: "Pullback low, all",
        rule: "pullback",
        n_fills: 20,
        avg_entry: "10:40",
        median_entry: "10:15",
        avg_stop_pct: 1.25,
        trades_per_day: 3.4,
        tape_days: 60,
        horizons: {},
      }),
    ).toBe("All enters at 10:40 on average (median 10:15). The stop averages 1.25% under the entry. 3.4 trades per day.");
    expect(
      reclaimSentence({
        books: {},
        order: [],
        panels: [],
        definition: "",
        best: { id: "lod_first", label: "Low of day, first", avg_r: 0.08, n_days: 40, n_trades: 40, vs_rma_first: -0.21 },
        benchmark: { label: "10:30 first", avg_r: 0.29, n_days: 58, n_trades: 58 },
      }),
    ).toBe("Low of day, first is the best of these books by day 3 at +0.08R per morning. The 10:30 first-name RMA book is +0.29R by day 3. Paired against that book it is -0.21R.");
    expect(reclaimSentence(undefined)).toBeNull();
  });
});
