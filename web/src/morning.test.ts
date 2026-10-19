import { describe, expect, it } from "vitest";
import {
  bestSentence,
  crossNote,
  crossSentence,
  pullbackNote,
  pullbackSentence,
  sweepSentence,
  windowNote,
  windowSentence,
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

  it("notes a 5-minute Strat pullback and sets it next to the 10:30 rank-tie books", () => {
    expect(
      pullbackNote({
        id: "pb1100_first",
        label: "11:00 first",
        title: "11:00 first",
        cutoff: "11:00",
        n_fills: 40,
        avg_entry: "10:05",
        median_entry: "9:55",
        avg_stop_pct: 1.1,
        avg_risk_dollars: 2.4,
        avg_rma_risk_dollars: 4.8,
        avg_entry_saved_pct: 0.85,
        n_paired: 36,
        trades_per_day: 1,
        tape_days: 60,
        horizons: {},
      }),
    ).toBe(
      "11:00 first enters at 10:05 on average (median 9:55). The stop averages 1.10% under the entry. Risk per share averages $2.40, against $4.80 at the 10:30 entry on the same name. Versus that 10:30 price the pullback entry is +0.85% (36 paired fills; positive means a lower entry).",
    );
    expect(
      pullbackSentence({
        books: {},
        order: [],
        panels: [],
        definition: "",
        best: { id: "pb1100_first", label: "11:00 first", avg_r: 0.4, n_days: 50, n_trades: 50, vs_rank_first: -0.45 },
        benchmark: {
          first: { label: "10:30 rank first", avg_r: 0.85, n_days: 58, n_trades: 58 },
          two: { label: "10:30 rank first 2", avg_r: 0.68, n_days: 58, n_trades: 116 },
        },
      }),
    ).toBe(
      "11:00 first is the best of these pullback books by day 3 at +0.40R per morning. The 10:30 rank-tie first book is +0.85R by day 3. First 2 is +0.68R. Paired against the rank-tie first book it is -0.45R.",
    );
    expect(pullbackSentence(undefined)).toBeNull();
  });

  it("notes the 10:00 to 10:30 pullback and how many mornings filled", () => {
    const book = {
      id: "win_time_two",
      label: "Time first 2",
      title: "10:00–10:30, first 2 by time",
      cutoff: "win",
      n_fills: 20,
      avg_entry: "10:12",
      median_entry: "10:10",
      avg_stop_pct: 1.4,
      avg_risk_dollars: 3.2,
      avg_rma_risk_dollars: 4.1,
      avg_entry_saved_pct: 0.4,
      n_paired: 18,
      trades_per_day: 1.2,
      tape_days: 60,
      mornings: { "0": 30, "1": 12, "2": 18 },
      horizons: {},
    };
    expect(windowNote(book)).toBe(
      "Time first 2 enters at 10:12 on average (median 10:10). The stop averages 1.40% under the entry. Risk per share averages $3.20, against $4.10 at the 10:30 entry on the same name. Versus that 10:30 price the pullback entry is +0.40% (18 paired fills; positive means a lower entry). Mornings with 0, 1, or 2 fills: 30, 12, 18.",
    );
    expect(
      windowSentence(
        {
          books: {},
          order: [],
          refs: [],
          definition: "",
          triggers: { "0": 10, "1": 20, "2": 15, more: 5 },
          best: { id: "win_time_two", label: "10:00–10:30, first 2 by time", avg_r: 0.2, n_days: 40, n_trades: 70, vs_rank_first: -0.65, vs_rank_two: -0.48 },
        },
        {
          first: { label: "10:30 rank first", avg_r: 0.85, n_days: 58, n_trades: 58 },
          two: { label: "10:30 rank first 2", avg_r: 0.68, n_days: 58, n_trades: 116 },
        },
      ),
    ).toBe(
      "10:00–10:30, first 2 by time is the best of these 10:00 to 10:30 books by day 3 at +0.20R per morning. The 10:30 rank-tie first book is +0.85R by day 3. First 2 is +0.68R. Paired against the rank-tie first book it is -0.65R. Against first 2 it is -0.48R.",
    );
    expect(windowSentence(undefined, null)).toBeNull();
  });

  it("ranks a 10:30 stop sweep by day-3 R and names the tight stop", () => {
    const horizon = (r: number, total: number, slip: number) => ({
      n_days: 10,
      n_trades: 10,
      r_per_trade: r,
      total_r: total,
      avg_pct: r,
      total_pct: total,
      win_rate: 0.4,
      stop_hit_rate: 0.5,
      gap_count: 1,
      avg_mfe: 2,
      median_r: -1,
      best_r: 4,
      worst_r: -1.2,
      slip_r_per_trade: slip,
      slip_total_r: slip * 10,
    });
    const stop = (id: string, label: string, r: number, width: number, slip: number) => ({
      id,
      label,
      family: "percent",
      n_considered: 10,
      n_skipped: 0,
      n_fills: 10,
      avg_stop_pct: width,
      fast_stop_rate: 0.2,
      horizons: { d3: horizon(r, r * 10, slip) },
    });
    const book = {
      id: "first",
      label: "First",
      order: ["pct_050", "pct_025", "lod"],
      order_total: ["lod", "pct_050", "pct_025"],
      best_r: "pct_050",
      best_total: "lod",
      tight: "pct_025",
      stops: {
        pct_050: stop("pct_050", "0.50%", 1.1, 0.5, 0.9),
        pct_025: stop("pct_025", "0.25%", 1.08, 0.25, 0.7),
        lod: stop("lod", "Low of day", 0.85, 2.0, 0.84),
      },
    };
    expect(sweepSentence(book)).toBe(
      "0.50% is the best day-3 R per trade on First at +1.10R (10 fills, total +11.0R). Low of day is +0.85R per trade, total +8.5R. Low of day leads on total R at +8.5R. The tightest stop within 0.05R of that best is 0.25% at +1.08R per trade, average stop 0.25%. With 0.05% slippage on the stop exit it is +0.70R per trade.",
    );
    expect(sweepSentence(undefined)).toBeNull();
  });
});
