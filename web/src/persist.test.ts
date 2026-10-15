import { describe, expect, it } from "vitest";
import { DEFAULT_TAB, isTimeframe, pageTitle, readPersisted, restoreTarget, tabLocation, writePersisted } from "./persist";

class MemoryStorage implements Storage {
  private data = new Map<string, string>();
  get length() {
    return this.data.size;
  }
  clear() {
    this.data.clear();
  }
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  key(i: number) {
    return [...this.data.keys()][i] ?? null;
  }
  removeItem(k: string) {
    this.data.delete(k);
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
}

describe("persisted values", () => {
  it("round-trips through storage with the app prefix", () => {
    const s = new MemoryStorage();
    writePersisted("sectorsTf", "M", s);
    expect(s.getItem("strat:sectorsTf")).toBe('"M"');
    expect(readPersisted("sectorsTf", "W", s)).toBe("M");
  });

  it("falls back on missing or corrupt values", () => {
    const s = new MemoryStorage();
    expect(readPersisted("detailTf", "W", s)).toBe("W");
    s.setItem("strat:detailTf", "{not json");
    expect(readPersisted("detailTf", "W", s)).toBe("W");
  });
});

describe("tab restore", () => {
  it("records only the top-level tabs, keeping their query", () => {
    expect(tabLocation("/sectors", "")).toBe("/sectors");
    expect(tabLocation("/market", "")).toBe("/market");
    expect(tabLocation("/", "?sector=Energy")).toBe("/?sector=Energy");
    expect(tabLocation("/watchlist", "")).toBe("/watchlist");
    expect(tabLocation("/positions", "")).toBe("/positions");
    expect(tabLocation("/stock/AAPL", "")).toBeNull();
  });

  it("reopens the last tab on a bare visit", () => {
    expect(restoreTarget("/", "", "/sectors")).toBe("/sectors");
    expect(restoreTarget("/", "", "/market")).toBe("/market");
    expect(restoreTarget("/", "", "/watchlist")).toBe("/watchlist");
    expect(restoreTarget("/", "", "/positions")).toBe("/positions");
    expect(restoreTarget("/", "", "/?sector=Health%20Care")).toBe("/?sector=Health%20Care");
  });

  it("defaults first-time visitors (or unusable saved values) to State of the Market", () => {
    expect(restoreTarget("/", "", null)).toBe("/market");
    expect(restoreTarget("/", "", "/evil")).toBe("/market");
    expect(DEFAULT_TAB).toBe("/market");
  });

  it("keeps the Stock Scanner when it was the last tab", () => {
    expect(restoreTarget("/", "", "/")).toBeNull();
  });

  it("never overrides deep links", () => {
    expect(restoreTarget("/sectors", "", "/")).toBeNull();
    expect(restoreTarget("/market", "", "/watchlist")).toBeNull();
    expect(restoreTarget("/watchlist", "", null)).toBeNull();
    expect(restoreTarget("/stock/TDY", "", "/sectors")).toBeNull();
    expect(restoreTarget("/", "?sector=Energy", "/sectors")).toBeNull();
    expect(restoreTarget("/", "?sector=Energy", null)).toBeNull();
  });

  it("titles each page after its tab", () => {
    expect(pageTitle("/")).toBe("Stock Scanner · Strat Scanner");
    expect(pageTitle("/sectors")).toBe("Sectors · Strat Scanner");
    expect(pageTitle("/market")).toBe("State of the Market · Strat Scanner");
    expect(pageTitle("/watchlist")).toBe("Watchlist · Strat Scanner");
    expect(pageTitle("/positions")).toBe("Positions · Strat Scanner");
    expect(pageTitle("/stock/brk-b")).toBe("BRK-B · Strat Scanner");
    expect(pageTitle("/nope")).toBe("Strat Scanner");
  });

  it("validates timeframes", () => {
    expect(isTimeframe("W")).toBe(true);
    expect(isTimeframe("Y")).toBe(false);
    expect(isTimeframe(null)).toBe(false);
  });
});
