import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Breadth } from "../api";
import { adRatio } from "../market";
import { BreadthPanel } from "./Breadth";

const base: Breadth = {
  nasi: null,
  fear_greed: null,
  issues: { advancing: 383, declining: 261, unchanged: 2, names: 646 },
  highs_lows: null,
};
const nasdaq = {
  advancing: 2105,
  declining: 2833,
  unchanged: 154,
  as_of: "4:15 PM EDT 10/22/26",
  session: "2026-10-22",
};

describe("adRatio", () => {
  it("reads the leading side", () => {
    expect(adRatio(2105, 2833)).toEqual({ text: "1.3 to 1", decliners: true });
    expect(adRatio(383, 261)).toEqual({ text: "1.5 to 1", decliners: false });
    expect(adRatio(0, 10)).toBeNull();
  });
});

describe("Advancers vs decliners card", () => {
  it("stacks the Nasdaq row below the universe row", () => {
    const html = renderToStaticMarkup(<BreadthPanel breadth={{ ...base, nasdaq_issues: nasdaq }} />);
    const universe = html.indexOf(">Universe<");
    const nas = html.indexOf(">Nasdaq<");
    expect(universe).toBeGreaterThan(-1);
    expect(nas).toBeGreaterThan(universe);
    expect(html).toContain("2,105 up");
    expect(html).toContain("2,833 down");
    expect(html).toContain('<span class="red-text">(1.3 to 1)</span>');
    expect(html).toContain('<span class="green-text">(1.5 to 1)</span>');
    expect(html).toContain("WSJ markets diary, 4:15 PM EDT 10/22/26");
  });

  it("hides the Nasdaq row (and keeps the universe bar unchanged) when the diary is missing", () => {
    const html = renderToStaticMarkup(<BreadthPanel breadth={{ ...base, nasdaq_issues: null }} />);
    expect(html).not.toContain("Nasdaq");
    expect(html).not.toContain(">Universe<");
    expect(html).not.toContain("to 1)");
    expect(html).toContain("383 up");
  });

  it("has no emoji", () => {
    const html = renderToStaticMarkup(<BreadthPanel breadth={{ ...base, nasdaq_issues: nasdaq }} />);
    expect(html).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});

describe("New highs vs new lows card", () => {
  const extremes = { highs: 12, lows: 30, names: 646 };
  const nasdaqHL = { highs: 110, lows: 455, as_of: "4:15 PM EDT 10/22/26", session: "2026-10-22" };
  const card = (html: string) => html.slice(html.indexOf("New highs vs new lows"));

  it("stacks the Nasdaq row below the universe row with the leading side's ratio", () => {
    const html = card(
      renderToStaticMarkup(
        <BreadthPanel breadth={{ ...base, highs_lows: extremes, nasdaq_highs_lows: nasdaqHL }} />,
      ),
    );
    const universe = html.indexOf(">Universe<");
    const nas = html.indexOf(">Nasdaq<");
    expect(universe).toBeGreaterThan(-1);
    expect(nas).toBeGreaterThan(universe);
    expect(html).toContain('<span class="green-text">110 highs</span>');
    expect(html).toContain('<span class="red-text">455 lows</span>');
    expect(html).toContain('<span class="red-text">(4.1 to 1)</span>');
    expect(html).toContain('<span class="red-text">(2.5 to 1)</span>');
    expect(html).toContain("WSJ markets diary, 4:15 PM EDT 10/22/26");
    expect(html).not.toMatch(/\p{Extended_Pictographic}/u);
  });

  it("leaves the universe card as it was when the Nasdaq reading is missing", () => {
    const html = card(
      renderToStaticMarkup(<BreadthPanel breadth={{ ...base, highs_lows: extremes, nasdaq_highs_lows: null }} />),
    );
    expect(html).not.toContain("Nasdaq");
    expect(html).not.toContain(">Universe<");
    expect(html).not.toContain("to 1)");
    expect(html).toContain("12 highs");
  });

  it("shows the Nasdaq row alone while the universe extremes are still loading", () => {
    const html = renderToStaticMarkup(
      <BreadthPanel breadth={{ ...base, highs_lows: null, nasdaq_highs_lows: nasdaqHL }} />,
    );
    expect(card(html)).toContain(">Nasdaq<");
    expect(card(html)).toContain("455 lows");
  });
});
