import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Trend } from "../api";
import { MARKET_SCORE_MESSAGES, RAGNAR_MOODS, ragnarFor } from "../market";
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

describe("score message color", () => {
  it("has no day-direction color class; it takes the trend call's color from the card", () => {
    for (const call of ["on", "caution", "off"] as const) {
      const html = renderToStaticMarkup(<MarketMood trend={trend(call, 4)} days={days} />);
      expect(html).toContain(`market-mood ${call}`);
      expect(html).toContain('class="market-score-msg"');
      expect(html).not.toMatch(/market-score-msg (red|green)-text/);
    }
  });

  it("uses the same color as the trend label for each call (styles.css)", () => {
    const css = readFileSync(resolve(__dirname, "../styles.css"), "utf8");
    const colors: Record<string, string> = { on: "var(--green)", off: "var(--red)", caution: "var(--yellow)" };
    for (const [call, color] of Object.entries(colors)) {
      const rule = new RegExp(`\\.trend-banner\\.${call} \\.trend-label, \\.trend-banner\\.${call} \\.market-score-msg \\{ color: ${color.replace(/[()]/g, "\\$&")}; \\}`);
      expect(css).toMatch(rule);
    }
  });
});

describe("no emoji or icon glyphs on the market card", () => {
  // Pictographs, dingbats / misc symbols, variation selectors and regional indicators. Ragnar's images carry the mood.
  const GLYPH = /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{FE0F}\u{1F1E6}-\u{1F1FF}]/u;

  it("has plain-text score messages", () => {
    for (const message of MARKET_SCORE_MESSAGES) expect(message).not.toMatch(GLYPH);
    expect(MARKET_SCORE_MESSAGES[1]).toBe("Barely a pulse. Cash is a position, and today it's the best one.");
  });

  it("renders no glyphs for any call and score, and keeps Ragnar and the chips", () => {
    for (const call of ["on", "caution", "off"] as const) {
      for (let score = 0; score <= 9; score++) {
        const html = renderToStaticMarkup(<MarketMood trend={trend(call, score)} days={days} issues={{ advancing: 100, declining: 400, unchanged: 0, names: 500 }} />);
        expect(html).not.toMatch(GLYPH);
        expect(html).toContain(`src="/ragnar/ragnar-${score}.webp"`);
        expect(html.match(/class="trend-ma /g)).toHaveLength(9);
      }
    }
  });
});
