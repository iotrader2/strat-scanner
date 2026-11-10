import { afterEach, describe, expect, it, vi } from "vitest";
import { api, type ScanRow } from "./api";
import { sortRows } from "./components/ScanTable";
import { normalizeTicker, watchSetupGroups, watchedRows, withSymbol } from "./watchlist";

const row = (symbol: string, extra: Partial<ScanRow> = {}) => ({ symbol, score: 50, has_setup: true, ...extra }) as ScanRow;

describe("watchlist toggling", () => {
  it("appends new symbols once, in insertion order", () => {
    expect(withSymbol(["TDY"], "AAPL", true)).toEqual(["TDY", "AAPL"]);
    expect(withSymbol(["TDY", "AAPL"], "TDY", true)).toEqual(["TDY", "AAPL"]);
  });

  it("removes symbols and ignores ones that are not watched", () => {
    expect(withSymbol(["TDY", "AAPL"], "TDY", false)).toEqual(["AAPL"]);
    expect(withSymbol(["AAPL"], "MSFT", false)).toEqual(["AAPL"]);
  });

  it("hides rows that were removed before the server replied", () => {
    const rows = [row("TDY"), row("AAPL", { has_setup: false, setup: null })];
    expect(watchedRows(rows, ["AAPL"]).map((r) => r.symbol)).toEqual(["AAPL"]);
  });
});

describe("Add symbol input", () => {
  it("trims and upper-cases what was typed", () => {
    expect(normalizeTicker("  mrna ")).toBe("MRNA");
    expect(normalizeTicker("brk.b")).toBe("BRK.B");
    expect(normalizeTicker("   ")).toBe("");
  });
});

describe("watchlist setup column", () => {
  it("groups a side's setups and collapses moving-average periods", () => {
    expect(watchSetupGroups([
      { kind: "episodic-pivot", label: "Episodic Pivot", side: "long" },
      { kind: "delayed-hvc", label: "Delayed High Volume Close", side: "long" },
      { kind: "ema-crossback", label: "EMA Crossback", side: "long" },
    ])).toEqual([{ side: "long", text: "EP, Delayed HVC, EMA Crossback" }]);
    expect(watchSetupGroups([
      { kind: "ma-overcut-fail", label: "MA Overcut and Fail (20-day)", side: "short", period: 20 },
      { kind: "ma-overcut-fail", label: "MA Overcut and Fail (10-day)", side: "short", period: 10 },
    ])).toEqual([{ side: "short", text: "MA Overcut Fail 10/20" }]);
  });

  it("shows nothing for a hand-added name that does not qualify", () => {
    expect(watchSetupGroups(undefined)).toEqual([]);
    expect(watchSetupGroups([])).toEqual([]);
  });

  it("keeps long and short on their own lines", () => {
    expect(watchSetupGroups([
      { kind: "flat-base-breakout", label: "Flat Base Breakout", side: "long" },
      { kind: "ma-overcut-fail", label: "MA Overcut and Fail (10-day)", side: "short", period: 10 },
    ])).toEqual([
      { side: "long", text: "Flat Base" },
      { side: "short", text: "MA Overcut Fail 10" },
    ]);
  });
});

describe("watchlist table", () => {
  it("keeps names without a setup and sorts them by score like the scanner", () => {
    const rows = [row("A", { score: 20, has_setup: false }), row("B", { score: 90 }), row("C", { score: 55 })];
    expect(sortRows(rows, "score", -1).map((r) => r.symbol)).toEqual(["B", "C", "A"]);
  });
});

describe("watchlist API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  const stubFetch = () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ symbols: [], rows: [], missing: [] })));
    vi.stubGlobal("fetch", fetch);
    return fetch;
  };

  it("adds with a JSON POST", async () => {
    const fetch = stubFetch();
    await api.watch("TDY");
    expect(fetch).toHaveBeenCalledWith("/api/watchlist", expect.objectContaining({ method: "POST", body: '{"symbol":"TDY"}' }));
  });

  it("surfaces the server's message when a ticker does not exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "ZZZZQX was not found on Yahoo Finance" }), { status: 404 })),
    );
    await expect(api.watch("ZZZZQX")).rejects.toMatchObject({ status: 404, message: "ZZZZQX was not found on Yahoo Finance" });
  });

  it("removes with DELETE on the symbol path", async () => {
    const fetch = stubFetch();
    await api.unwatch("BRK-B");
    expect(fetch).toHaveBeenCalledWith("/api/watchlist/BRK-B", { method: "DELETE" });
  });
});
