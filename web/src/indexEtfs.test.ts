import { describe, expect, it } from "vitest";
import { isIndexEtf, keepIndexEtf } from "./indexEtfs";

const qqq = { symbol: "QQQ", kind: "etf", indexes: "benchmark" };
const spy = { symbol: "SPY", kind: "etf", indexes: "benchmark" };
const iwm = { symbol: "IWM", kind: "etf", indexes: "benchmark" };
const xlk = { symbol: "XLK", kind: "etf", indexes: "spdr" };
const nvda = { symbol: "NVDA", kind: "stock", indexes: "SP500;NDX" };

describe("isIndexEtf", () => {
  it("is QQQ, SPY and IWM only", () => {
    expect([qqq, spy, iwm].every(isIndexEtf)).toBe(true);
    expect(isIndexEtf(xlk)).toBe(false);
    expect(isIndexEtf(nvda)).toBe(false);
  });

  it("falls back to the symbol when the group tag is missing", () => {
    expect(isIndexEtf({ symbol: "SPY", kind: "etf" })).toBe(true);
    expect(isIndexEtf({ symbol: "SPY", kind: "stock" })).toBe(false);
  });
});

describe("keepIndexEtf", () => {
  it("keeps the index ETFs in the ETFs view whatever the Setups option", () => {
    expect(keepIndexEtf(qqq, "etf")).toBe(true);
    expect(keepIndexEtf(xlk, "etf")).toBe(false);
  });

  it("does not change Stocks + ETFs or Stocks", () => {
    expect(keepIndexEtf(qqq, "all")).toBe(false);
    expect(keepIndexEtf(qqq, "stock")).toBe(false);
  });
});
