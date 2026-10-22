import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MARKET_SCORE_MESSAGES } from "../market";
import { MarketScoreBanner } from "./MarketScoreBanner";

describe("MarketScoreBanner", () => {
  it("shows only the message, with no score label or per-index breakdown", () => {
    const html = renderToStaticMarkup(<MarketScoreBanner trend={{ score: 1 }} />);
    expect(html).toContain("Barely a pulse");
    expect(html).not.toMatch(/Market score|\/9|\/3|QQQ|SPY|IWM/);
  });

  it("goes from red at 0 to green at 9", () => {
    expect(renderToStaticMarkup(<MarketScoreBanner trend={{ score: 0 }} />)).toContain("hsl(0, 85%, 55%)");
    const top = renderToStaticMarkup(<MarketScoreBanner trend={{ score: 9 }} />);
    expect(top).toContain("hsl(120, 85%, 55%)");
    expect(top).toContain(MARKET_SCORE_MESSAGES[9].slice(3));
  });
});
