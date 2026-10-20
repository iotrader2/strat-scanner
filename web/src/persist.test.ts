import { describe, expect, it } from "vitest";
import {
  DEFAULT_TAB,
  RETIRED_FILTER_KEYS,
  clearRetiredFilters,
  isTimeframe,
  pageTitle,
  readPersisted,
  restoreTarget,
  tabLocation,
  writePersisted,
} from "./persist";

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
    writePersisted("themesTf", "M", s);
    expect(s.getItem("strat:themesTf")).toBe('"M"');
    expect(readPersisted("themesTf", "W", s)).toBe("M");
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
    expect(tabLocation("/themes", "")).toBe("/themes");
    expect(tabLocation("/market", "")).toBe("/market");
    expect(tabLocation("/", "?theme=memory")).toBe("/?theme=memory");
    expect(tabLocation("/watchlist", "")).toBe("/watchlist");
    expect(tabLocation("/positions", "")).toBe("/positions");
    expect(tabLocation("/stock/AAPL", "")).toBeNull();
  });

  it("reopens the last tab on a bare visit", () => {
    expect(restoreTarget("/", "", "/themes")).toBe("/themes");
    expect(restoreTarget("/", "", "/sectors")).toBe("/themes");
    expect(restoreTarget("/", "", "/market")).toBe("/market");
    expect(restoreTarget("/", "", "/watchlist")).toBe("/watchlist");
    expect(restoreTarget("/", "", "/positions")).toBe("/positions");
    expect(restoreTarget("/", "", "/?theme=cybersecurity")).toBe("/?theme=cybersecurity");
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
    expect(restoreTarget("/themes", "", "/")).toBeNull();
    expect(restoreTarget("/market", "", "/watchlist")).toBeNull();
    expect(restoreTarget("/watchlist", "", null)).toBeNull();
    expect(restoreTarget("/stock/TDY", "", "/themes")).toBeNull();
    expect(restoreTarget("/", "?theme=memory", "/themes")).toBeNull();
    expect(restoreTarget("/", "?theme=memory", null)).toBeNull();
  });

  it("titles each page after its tab", () => {
    expect(pageTitle("/")).toBe("Stock Scanner · TiltKiller");
    expect(pageTitle("/themes")).toBe("Themes · TiltKiller");
    expect(pageTitle("/market")).toBe("State of the Market · TiltKiller");
    expect(pageTitle("/watchlist")).toBe("Watchlist · TiltKiller");
    expect(pageTitle("/positions")).toBe("Positions · TiltKiller");
    expect(pageTitle("/stock/brk-b")).toBe("BRK-B · TiltKiller");
    expect(pageTitle("/nope")).toBe("TiltKiller");
  });

  it("validates timeframes", () => {
    expect(isTimeframe("W")).toBe(true);
    expect(isTimeframe("Y")).toBe(false);
    expect(isTimeframe(null)).toBe(false);
  });
});


describe("clearRetiredFilters", () => {
  it("drops saved Continuity selections (both old keys) and keeps every other filter", () => {
    const storage = new MemoryStorage();
    writePersisted("continuityFilter", "mw", storage);
    writePersisted("continuity", "full", storage);
    writePersisted("kind", "stock", storage);
    writePersisted("atrPct", [2, 6], storage);
    clearRetiredFilters(storage);
    expect(RETIRED_FILTER_KEYS).toEqual(["continuityFilter", "continuity"]);
    expect(storage.getItem("strat:continuityFilter")).toBeNull();
    expect(storage.getItem("strat:continuity")).toBeNull();
    expect(readPersisted("kind", "all", storage)).toBe("stock");
    expect(readPersisted("atrPct", null, storage)).toEqual([2, 6]);
  });

  it("does nothing when storage throws", () => {
    const broken = { removeItem: () => { throw new Error("denied"); } } as unknown as Storage;
    expect(() => clearRetiredFilters(broken)).not.toThrow();
  });
});
