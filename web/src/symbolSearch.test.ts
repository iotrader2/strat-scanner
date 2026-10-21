import { describe, expect, it } from "vitest";
import { matchesSymbol, pinExactSymbol, sanitizeSymbol, sanitizeWithCaret, SYMBOL_SEARCH_MAX } from "./symbolSearch";

describe("sanitizeSymbol", () => {
  it("uppercases as you type", () => {
    expect(sanitizeSymbol("nvda")).toBe("NVDA");
    expect(sanitizeSymbol("Nv")).toBe("NV");
  });

  it("keeps A-Z, 0-9, dots and dashes and strips everything else", () => {
    expect(sanitizeSymbol(" brk.b ")).toBe("BRK.B");
    expect(sanitizeSymbol("brk-b")).toBe("BRK-B");
    expect(sanitizeSymbol("$nvda!")).toBe("NVDA");
    expect(sanitizeSymbol("nvidia corp")).toBe("NVIDIACORP");
    expect(sanitizeSymbol("ä1é_2/3")).toBe("123");
  });

  it("caps the length", () => {
    expect(sanitizeSymbol("a".repeat(30))).toHaveLength(SYMBOL_SEARCH_MAX);
  });
});

describe("sanitizeWithCaret", () => {
  it("keeps the caret after the same character when typing in the middle", () => {
    // "NVA" with the caret after "NV", the user types "d" -> "NVdA", caret 3
    expect(sanitizeWithCaret("NVdA", 3)).toEqual({ value: "NVDA", caret: 3 });
  });

  it("does not advance the caret for a stripped character", () => {
    // "NV" + space typed at the end: caret 3 -> 2
    expect(sanitizeWithCaret("NV ", 3)).toEqual({ value: "NV", caret: 2 });
    // a space typed at the start
    expect(sanitizeWithCaret(" NVDA", 1)).toEqual({ value: "NVDA", caret: 0 });
  });

  it("puts the caret at the end when the browser gives none", () => {
    expect(sanitizeWithCaret("mu", null)).toEqual({ value: "MU", caret: 2 });
  });
});

describe("matchesSymbol", () => {
  it("is a prefix match on the ticker", () => {
    expect(matchesSymbol("NVDA", "NV")).toBe(true);
    expect(matchesSymbol("NVDA", "nv")).toBe(true);
    expect(matchesSymbol("NVDA", "VDA")).toBe(false); // not a contains match
    expect(matchesSymbol("SNOW", "NO")).toBe(false);
  });

  it("matches everything for an empty or all-invalid query", () => {
    expect(matchesSymbol("AAPL", "")).toBe(true);
    expect(matchesSymbol("AAPL", "  ")).toBe(true);
  });

  it("handles class shares", () => {
    expect(matchesSymbol("BRK-B", "BRK-")).toBe(true);
    expect(matchesSymbol("BRK-B", "brk-b")).toBe(true);
  });
});

describe("pinExactSymbol", () => {
  const rows = [{ symbol: "MUU" }, { symbol: "MSTR" }, { symbol: "MU" }, { symbol: "MRNA" }];

  it("moves the exact match to the top and keeps the rest in order", () => {
    expect(pinExactSymbol(rows, "mu").map((r) => r.symbol)).toEqual(["MU", "MUU", "MSTR", "MRNA"]);
  });

  it("leaves the rows alone without an exact match or query", () => {
    expect(pinExactSymbol(rows, "M")).toBe(rows);
    expect(pinExactSymbol(rows, "")).toBe(rows);
    expect(pinExactSymbol(rows, "MUU")).toBe(rows); // already first
  });
});
