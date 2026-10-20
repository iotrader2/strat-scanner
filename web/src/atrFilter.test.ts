import { describe, expect, it } from "vitest";
import {
  ATR_PCT_DEFAULT,
  ATR_PCT_RANGE,
  atrPercent,
  formatAtrRange,
  isAtrFilterActive,
  normalizeAtrRange,
  passesAtr,
} from "./atrFilter";
import { readPersisted, writePersisted } from "./persist";

function memoryStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, String(v)),
  };
}

describe("atrPercent", () => {
  it("is the ATR as a percent of price, rounded like the backend", () => {
    expect(atrPercent(2.5, 100)).toBe(2.5);
    expect(atrPercent(1.234, 50)).toBe(2.47);
    expect(atrPercent(3, 0)).toBeNull();
    expect(atrPercent(null, 100)).toBeNull();
    expect(atrPercent(2, undefined)).toBeNull();
  });
});

describe("ATR % filter", () => {
  const row = (atr_pct: number | null) => ({ atr_pct });

  it("defaults to the full range and filters nothing, not even rows without ATR", () => {
    expect(ATR_PCT_DEFAULT).toEqual([ATR_PCT_RANGE.min, ATR_PCT_RANGE.max]);
    expect(isAtrFilterActive(ATR_PCT_DEFAULT)).toBe(false);
    for (const r of [row(0.1), row(5), row(40), row(null)]) expect(passesAtr(r, ATR_PCT_DEFAULT)).toBe(true);
    expect(formatAtrRange(ATR_PCT_DEFAULT)).toBe("Any");
  });

  it("keeps names inside the range, bounds included", () => {
    const range = [2, 6] as const;
    expect(passesAtr(row(2), range)).toBe(true);
    expect(passesAtr(row(4.1), range)).toBe(true);
    expect(passesAtr(row(6), range)).toBe(true);
    expect(passesAtr(row(1.99), range)).toBe(false);
    expect(passesAtr(row(6.01), range)).toBe(false);
    expect(passesAtr(row(null), range)).toBe(false);
    expect(formatAtrRange(range)).toBe("2% – 6%");
  });

  it("treats the top of the slider as no upper limit", () => {
    const range = [3, ATR_PCT_RANGE.max] as const;
    expect(passesAtr(row(30), range)).toBe(true);
    expect(passesAtr(row(2.5), range)).toBe(false);
    expect(formatAtrRange(range)).toBe("≥ 3%");
    expect(formatAtrRange([0, 4.5])).toBe("≤ 4.5%");
    expect(formatAtrRange([1.25, 4.5])).toBe("1.25% – 4.5%");
  });
});

describe("normalizeAtrRange (saved slider state)", () => {
  it("clamps, snaps to the step and orders the handles", () => {
    expect(normalizeAtrRange([6, 2])).toEqual([2, 6]);
    expect(normalizeAtrRange([-3, 99])).toEqual([ATR_PCT_RANGE.min, ATR_PCT_RANGE.max]);
    expect(normalizeAtrRange([1.1, 3.9])).toEqual([1, 4]);
  });

  it("falls back to the default for anything that is not a two-number range", () => {
    for (const bad of [null, undefined, "x", 3, [], [1], [1, 2, 3], ["a", 2], { 0: 1, 1: 2 }]) {
      expect(normalizeAtrRange(bad)).toEqual(ATR_PCT_DEFAULT);
    }
  });

  it("round-trips through the persisted filter store", () => {
    const storage = memoryStorage();
    expect(normalizeAtrRange(readPersisted("atrPct", ATR_PCT_DEFAULT, storage))).toEqual(ATR_PCT_DEFAULT);
    writePersisted("atrPct", [2.25, 7], storage);
    expect(storage.getItem("strat:atrPct")).toBe("[2.25,7]");
    expect(normalizeAtrRange(readPersisted("atrPct", ATR_PCT_DEFAULT, storage))).toEqual([2.25, 7]);
    storage.setItem("strat:atrPct", "not json");
    expect(normalizeAtrRange(readPersisted("atrPct", ATR_PCT_DEFAULT, storage))).toEqual(ATR_PCT_DEFAULT);
  });
});
