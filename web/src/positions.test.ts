import { afterEach, describe, expect, it, vi } from "vitest";
import { api, errorDetail, type ScanRow } from "./api";
import { sortBy } from "./components/ScanTable";
import { daysBetween, fmtPnl, parseEntry, positionStats, todayIso } from "./positions";

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
