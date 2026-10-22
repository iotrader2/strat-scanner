import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Trend } from "../api";
import { MARKET_SCORE_MESSAGES, RAGNAR_MOODS, moodTone, ragnarFor } from "../market";
import { MarketMood } from "./MarketMood";

const avg = (period: number, above: boolean) => ({ period, value: 100, above });
const index = (symbol: string, above: [boolean, boolean, boolean]) => ({
  symbol,
  price: 100,
  averages: [avg(6, above[0]), avg(20, above[1]), avg(50, above[2])],
  points: above.filter(Boolean).length,
  max_points: 3,
});
const trend = (call: Trend["call"], score: number): Trend => ({
  call,
  score,
  score_max: 9,
  indexes: [index("QQQ", [false, false, false]), index("SPY", [false, false, false]), index("IWM", [true, false, false])],
});
const days = [
  { symbol: "QQQ", change_pct: -2.82 },
  { symbol: "SPY", change_pct: -1.35 },
  { symbol: "IWM", change_pct: -0.26 },
];

describe("ragnarFor", () => {
  it("maps each score 0–9 to ragnar-N, clamping odd values", () => {
    expect(RAGNAR_MOODS).toHaveLength(10);
    for (let n = 0; n <= 9; n++) expect(ragnarFor(n).src).toBe(`/ragnar/ragnar-${n}.webp`);
    expect(ragnarFor(-4).src).toBe("/ragnar/ragnar-0.webp");
    expect(ragnarFor(12).src).toBe("/ragnar/ragnar-9.webp");
    expect(ragnarFor(Number.NaN).src).toBe("/ragnar/ragnar-0.webp");
    expect(new Set(RAGNAR_MOODS.map((m) => m.alt)).size).toBe(10);
  });
});

describe("MarketMood", () => {
  it("is one card: Ragnar, trend label and detail, the score message, then the index chips", () => {
    const html = renderToStaticMarkup(<MarketMood trend={trend("caution", 1)} days={days} />);
    expect(html.match(/<section/g)).toHaveLength(1);
    const order = [
      'src="/ragnar/ragnar-1.webp"',
      "CAUTION",
      "The indexes are split around their 6, 20 and 50 day averages.",
      MARKET_SCORE_MESSAGES[1].replace("'", "&#x27;"),
      "QQQ",
      "SPY",
      "IWM",
    ].map((s) => html.indexOf(s));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(html).toContain('alt="Ragnar holding a skull"');
    expect(html.match(/trend-ma /g)).toHaveLength(9);
    expect(html.match(/trend-ma above/g)).toHaveLength(1);
  });

  it("has no score label", () => {
    const html = renderToStaticMarkup(<MarketMood trend={trend("off", 0)} days={days} />);
    expect(html).not.toMatch(/Market score|\/9/);
    expect(html).toContain("DO NOT TRADE");
    expect(html).toContain('src="/ragnar/ragnar-0.webp"');
  });

  it("takes the ring color from the trend call", () => {
    expect(renderToStaticMarkup(<MarketMood trend={trend("on", 9)} days={days} />)).toContain("trend-banner market-mood on");
    expect(renderToStaticMarkup(<MarketMood trend={trend("caution", 4)} days={days} />)).toContain("market-mood caution");
    expect(renderToStaticMarkup(<MarketMood trend={trend("off", 0)} days={days} />)).toContain("market-mood off smash");
  });
});

describe("moodTone", () => {
  it("is red when most indexes are down on the day, green otherwise, sum as tie-break", () => {
    expect(moodTone([-2.82, -1.35, -0.26])).toBe("red");
    expect(moodTone([-0.5, -0.1, 1.2])).toBe("red");
    expect(moodTone([0.5, 0.1, -1.2])).toBe("green");
    expect(moodTone([-1, 0, 0.4])).toBe("red");
    expect(moodTone([1, 0, -0.4])).toBe("green");
    expect(moodTone([0, 0, 0])).toBe("green");
    expect(moodTone([])).toBe("green");
  });

  it("colors the message with the same classes as the index moves", () => {
    const down = renderToStaticMarkup(<MarketMood trend={trend("caution", 1)} days={days} />);
    expect(down).toContain('class="market-score-msg red-text"');
    const up = days.map((d) => ({ ...d, change_pct: Math.abs(d.change_pct) }));
    expect(renderToStaticMarkup(<MarketMood trend={trend("caution", 1)} days={up} />)).toContain('class="market-score-msg green-text"');
  });
});
