import { afterEach, describe, expect, it, vi } from "vitest";
import { api, errorDetail, type ScanRow } from "./api";
import { sortBy } from "./components/ScanTable";
import {
  breakEven,
  daysBetween,
  fmtPnl,
  formatBreakEven,
  parseEntry,
  parseTrim,
  positionStats,
  realizedTrimPnl,
  remainingShares,
  todayIso,
  trimHistoryTitle,
  trimPreview,
} from "./positions";

describe("positionStats", () => {
  it("computes % gain, $ P/L and days held", () => {
    const s = positionStats({ entry_price: 100, shares: 50, entry_date: "2026-10-01" }, 112.5, "2026-10-15");
    expect(s.pct).toBeCloseTo(12.5);
    expect(s.pnl).toBeCloseTo(625);
    expect(s.days).toBe(14);
  });

  it("reports losses as negative", () => {
    const s = positionStats({ entry_price: 80, shares: 10, entry_date: "2026-10-15" }, 72, "2026-10-15");
    expect(s.pct).toBeCloseTo(-10);
    expect(s.pnl).toBeCloseTo(-80);
    expect(s.days).toBe(0);
  });

  it("has no $ P/L without shares", () => {
    expect(positionStats({ entry_price: 10, shares: null, entry_date: "2026-10-01" }, 11, "2026-10-02").pnl).toBeNull();
  });

  it("keeps unrealized P/L on the buy price for the remaining shares", () => {
    const s = positionStats({ entry_price: 100, shares: 75, entry_date: "2026-10-01" }, 110, "2026-10-20");
    expect(s.pct).toBeCloseTo(10);
    expect(s.pnl).toBeCloseTo(750);
  });

  it("counts calendar days across month and DST boundaries", () => {
    expect(daysBetween("2026-02-28", "2026-03-01")).toBe(1);
    expect(daysBetween("2026-03-07", "2026-03-09")).toBe(2);
    expect(daysBetween("2025-12-31", "2026-11-02")).toBe(306);
  });
});

describe("formatting", () => {
  it("formats signed dollar P/L", () => {
    expect(fmtPnl(1234.5)).toBe("+$1,234.50");
    expect(fmtPnl(-80)).toBe("−$80.00");
    expect(fmtPnl(0)).toBe("$0.00");
  });

  it("uses the local calendar date for today", () => {
    expect(todayIso(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });
});

describe("parseEntry", () => {
  const today = "2026-10-15";

  it("accepts price, optional shares and a past date", () => {
    expect(parseEntry({ price: "$1,250.40", shares: "", date: "2026-10-01" }, today)).toEqual({
      ok: true,
      entry_price: 1250.4,
      shares: null,
      entry_date: "2026-10-01",
    });
    expect(parseEntry({ price: "12", shares: "1,000", date: today }, today)).toMatchObject({ ok: true, shares: 1000 });
  });

  it("requires a price unless it may default to the last price", () => {
    expect(parseEntry({ price: " ", shares: "", date: today }, today)).toEqual({ ok: false, error: "Enter an entry price" });
    expect(parseEntry({ price: "", shares: "", date: today }, today, true)).toMatchObject({ ok: true, entry_price: null });
  });

  it("rejects bad numbers and future dates", () => {
    expect(parseEntry({ price: "-3", shares: "", date: today }, today).ok).toBe(false);
    expect(parseEntry({ price: "abc", shares: "", date: today }, today).ok).toBe(false);
    expect(parseEntry({ price: "10", shares: "0", date: today }, today).ok).toBe(false);
    expect(parseEntry({ price: "10", shares: "", date: "2026-10-16" }, today)).toEqual({
      ok: false,
      error: "Entry date can't be in the future",
    });
    expect(parseEntry({ price: "10", shares: "", date: "" }, today).ok).toBe(false);
  });
});

describe("trim dialog", () => {
  const held = { entry_price: 50, initial_shares: 100, trims: [{ shares: 25, price: 60 }] };

  it("previews remaining shares, this trim's realized P/L, and the new break-even", () => {
    const parsed = parseTrim({ price: "$80", shares: "25" }, remainingShares(held.initial_shares, held.trims));
    expect(parsed).toEqual({ ok: true, price: 80, shares: 25 });
    if (!parsed.ok) return;
    const preview = trimPreview(held, parsed);
    expect(preview.remaining).toBe(50);
    expect(preview.realized).toBeCloseTo(25 * (80 - 50));
    // (100 * 50 - 25 * 60 - 25 * 80) / 50 = 30
    expect(preview.breakEven).toBeCloseTo(30);
  });

  it("matches the cost-basis formula for one trim, several trims, and a free trade", () => {
    expect(breakEven(100, 50, [])).toBe(50);
    expect(breakEven(100, 50, [{ shares: 25, price: 60 }])).toBeCloseTo(3500 / 75);
    expect(realizedTrimPnl(50, [{ shares: 25, price: 60 }])).toBe(250);
    const lots = [{ shares: 20, price: 12 }, { shares: 30, price: 15 }];
    expect(breakEven(100, 10, lots)).toBeCloseTo(6.2);
    expect(realizedTrimPnl(10, lots)).toBeCloseTo(190);
    expect(breakEven(100, 10, [{ shares: 50, price: 20 }])).toBe(0);
    expect(breakEven(100, 10, [{ shares: 40, price: 30 }])).toBeCloseTo(-200 / 60);
    expect(formatBreakEven(0)).toEqual({ label: "Free", note: "Cost covered" });
    expect(formatBreakEven(-10)).toEqual({ label: "−10.00", note: "Free trade" });
    expect(formatBreakEven(46.666)).toEqual({ label: "46.67", note: null });
  });

  it("refuses a non-positive price or a sale of every share still held", () => {
    expect(parseTrim({ price: "", shares: "1" }, 10)).toMatchObject({ ok: false, error: "Enter a trim price" });
    expect(parseTrim({ price: "0", shares: "1" }, 10).ok).toBe(false);
    expect(parseTrim({ price: "-2", shares: "1" }, 10).ok).toBe(false);
    expect(parseTrim({ price: "abc", shares: "1" }, 10).ok).toBe(false);
    expect(parseTrim({ price: "10", shares: "" }, 10)).toMatchObject({ ok: false, error: "Enter the shares to trim" });
    expect(parseTrim({ price: "10", shares: "0" }, 10)).toMatchObject({ ok: false, error: "Shares must be greater than 0" });
    expect(parseTrim({ price: "10", shares: "-1" }, 10).ok).toBe(false);
    expect(parseTrim({ price: "1,200.5", shares: "1" }, 40)).toMatchObject({ ok: true, price: 1200.5, shares: 1 });
    for (const shares of ["10", "11", "10.0000001"]) {
      const parsed = parseTrim({ price: "15", shares }, 10);
      expect(parsed.ok).toBe(false);
      if (!parsed.ok) expect(parsed.error).toMatch(/Close position/);
    }
    expect(parseTrim({ price: "15", shares: "1" }, null)).toMatchObject({ ok: false, error: expect.stringMatching(/Edit entry/) });
    expect(parseTrim({ price: "15", shares: "1" }, 0).ok).toBe(false);
  });

  it("puts trim history and realized P/L in the row tooltip", () => {
    const title = trimHistoryTitle({
      entry_price: 50,
      shares: 100,
      remaining_shares: 75,
      break_even: 3500 / 75,
      realized_pnl: 250,
      trims: [{ id: 1, shares: 25, price: 60, trimmed_at: "2026-10-20T15:04:00+00:00" }],
    });
    expect(title).toContain("Buy 100 sh @ 50.00");
    expect(title).toContain("Remaining 75 sh");
    expect(title).toContain("46.67");
    expect(title).toContain("+$250.00");
    expect(title).toContain("25 sh @ 60.00");
  });
});

describe("positions table sorting", () => {
  it("sorts by a position column with missing values last", () => {
    const rows = ["A", "B", "C"].map((symbol) => ({ symbol }) as ScanRow);
    const gain: Record<string, number | null> = { A: -4, B: null, C: 9 };
    expect(sortBy(rows, (r) => gain[r.symbol], -1).map((r) => r.symbol)).toEqual(["C", "A", "B"]);
    expect(sortBy(rows, (r) => gain[r.symbol], 1).map((r) => r.symbol)).toEqual(["A", "C", "B"]);
  });
});

describe("positions API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  const stubFetch = () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ symbols: [], positions: [] })));
    vi.stubGlobal("fetch", fetch);
    return fetch;
  };

  it("opens with a JSON POST, leaving defaults to the server", async () => {
    const fetch = stubFetch();
    await api.openPosition({ symbol: "TDY", entry_price: null, shares: 5, entry_date: null });
    expect(fetch).toHaveBeenCalledWith(
      "/api/positions",
      expect.objectContaining({ method: "POST", body: '{"symbol":"TDY","entry_price":null,"shares":5,"entry_date":null}' }),
    );
  });

  it("edits with PUT, closes with DELETE and moves back with POST", async () => {
    const fetch = stubFetch();
    await api.updatePosition("BRK-B", { entry_price: 480, shares: null, entry_date: "2026-10-01" });
    expect(fetch).toHaveBeenLastCalledWith("/api/positions/BRK-B", expect.objectContaining({ method: "PUT" }));
    await api.closePosition("BRK-B");
    expect(fetch).toHaveBeenLastCalledWith("/api/positions/BRK-B", { method: "DELETE" });
    await api.positionToWatchlist("BRK-B");
    expect(fetch).toHaveBeenLastCalledWith("/api/positions/BRK-B/watchlist", { method: "POST" });
    await api.trimPosition("BRK-B", { shares: 2, price: 500 });
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/positions/BRK-B/trims",
      expect.objectContaining({ method: "POST", body: '{"shares":2,"price":500}' }),
    );
    await api.undoTrim("BRK-B", 7);
    expect(fetch).toHaveBeenLastCalledWith("/api/positions/BRK-B/trims/7", { method: "DELETE" });
  });

  it("surfaces validation messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: [{ msg: "Input should be greater than 0" }] }), { status: 422 })),
    );
    await expect(api.openPosition({ symbol: "TDY", entry_price: -1 })).rejects.toMatchObject({
      status: 422,
      message: "Input should be greater than 0",
    });
  });
});

describe("errorDetail", () => {
  it("reads string and validation-list details from FastAPI errors", () => {
    expect(errorDetail({ detail: "MSFT is already in Positions" })).toBe("MSFT is already in Positions");
    expect(errorDetail({ detail: [{ msg: "Input should be greater than 0" }] })).toBe("Input should be greater than 0");
    expect(errorDetail({ nope: 1 })).toBeNull();
    expect(errorDetail(null)).toBeNull();
  });
});
