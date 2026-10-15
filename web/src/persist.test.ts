import { describe, expect, it } from "vitest";
import { isTimeframe, readPersisted, restoreTarget, tabLocation, writePersisted } from "./persist";

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
    expect(tabLocation("/", "?sector=Energy")).toBe("/?sector=Energy");
    expect(tabLocation("/stock/AAPL", "")).toBeNull();
  });

  it("reopens the last tab on a bare visit", () => {
    expect(restoreTarget("/", "", "/sectors")).toBe("/sectors");
    expect(restoreTarget("/", "", "/?sector=Health%20Care")).toBe("/?sector=Health%20Care");
  });

  it("never overrides deep links or an already-correct tab", () => {
    expect(restoreTarget("/sectors", "", "/")).toBeNull();
    expect(restoreTarget("/stock/TDY", "", "/sectors")).toBeNull();
    expect(restoreTarget("/", "?sector=Energy", "/sectors")).toBeNull();
    expect(restoreTarget("/", "", "/")).toBeNull();
    expect(restoreTarget("/", "", null)).toBeNull();
    expect(restoreTarget("/", "", "/evil")).toBeNull();
  });

  it("validates timeframes", () => {
    expect(isTimeframe("W")).toBe(true);
    expect(isTimeframe("Y")).toBe(false);
    expect(isTimeframe(null)).toBe(false);
  });
});
