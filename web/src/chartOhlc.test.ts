// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { fmtOhlcPrice, ohlcParts, renderOhlc } from "./chartOhlc";

describe("chart OHLC readout", () => {
  it("formats prices to the cent, sub-dollar to 4 decimals", () => {
    expect(fmtOhlcPrice(123.456)).toBe("123.46");
    expect(fmtOhlcPrice(0.12345)).toBe("0.1235");
  });

  it("lists O H L C and colours by the candle", () => {
    const p = ohlcParts({ open: 10, high: 12.5, low: 9.75, close: 12 });
    expect(p.items).toEqual([["O", "10.00"], ["H", "12.50"], ["L", "9.75"], ["C", "12.00"]]);
    expect(p.up).toBe(true);
    expect(ohlcParts({ open: 12, high: 12.5, low: 9.75, close: 10 }).up).toBe(false);
  });

  it("renders into the element and clears without a bar", () => {
    const el = document.createElement("div");
    renderOhlc(el, { open: 10, high: 12.5, low: 9.75, close: 12 }, "2026-11-04");
    expect(el.textContent).toBe("2026-11-04O10.00H12.50L9.75C12.00");
    renderOhlc(el, null);
    expect(el.textContent).toBe("");
  });
});
