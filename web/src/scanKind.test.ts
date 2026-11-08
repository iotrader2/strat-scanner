import { describe, expect, it } from "vitest";
import { KINDS, KIND_LABELS, isKind, matchesKind } from "./scanKind";

const stock = { kind: "stock" };
const xlk = { kind: "etf", indexes: "spdr" };
const mud = { kind: "etf", indexes: "inverse" };

describe("Type filter", () => {
  it("offers inverse ETFs alone and with stocks", () => {
    expect(KINDS.map((k) => KIND_LABELS[k])).toEqual([
      "Stocks + ETFs", "Stocks", "ETFs", "Inverse ETFs", "Stocks + Inverse ETFs",
    ]);
    expect(isKind("stock_inverse") && !isKind("nope")).toBe(true);
  });

  it("matches rows by kind", () => {
    expect([stock, xlk, mud].map((r) => matchesKind(r, "inverse"))).toEqual([false, false, true]);
    expect([stock, xlk, mud].map((r) => matchesKind(r, "stock_inverse"))).toEqual([true, false, true]);
    expect([stock, xlk, mud].map((r) => matchesKind(r, "etf"))).toEqual([false, true, true]);
    expect([stock, xlk, mud].map((r) => matchesKind(r, "all"))).toEqual([true, true, true]);
  });
});
