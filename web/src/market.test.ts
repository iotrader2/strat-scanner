import { describe, expect, it } from "vitest";
import { marketRead } from "./market";

const row = (symbol: string, mw_green: boolean, full_continuity = false) => ({ symbol, mw_green, full_continuity });

describe("marketRead", () => {
  it("is green when every index has Monthly + Weekly continuity", () => {
    expect(marketRead([row("QQQ", true, true), row("SPY", true), row("IWM", true)])).toEqual({
      tone: "green",
      summary: "3 of 3 indexes have Monthly + Weekly green continuity (1 with full M+W+D)",
    });
  });

  it("is mixed or red otherwise", () => {
    expect(marketRead([row("QQQ", true), row("SPY", false), row("IWM", false)]).tone).toBe("mixed");
    expect(marketRead([row("QQQ", false), row("SPY", false), row("IWM", false)])).toEqual({
      tone: "red",
      summary: "0 of 3 indexes have Monthly + Weekly green continuity",
    });
  });

  it("handles missing data", () => {
    expect(marketRead([]).summary).toBe("No index data yet");
  });
});
