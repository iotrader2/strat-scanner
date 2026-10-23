import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ScanRow } from "../api";
import { ListTable } from "./ListTable";
import { ScanTable } from "./ScanTable";

const row = {
  symbol: "TEAM",
  name: "Atlassian Corporation",
  kind: "stock",
  theme: "software",
  theme_name: "Software & SaaS",
  price: 223.16,
  change_pct: -1.04,
  perf: { "1m": 18.29, "3m": 161.31, "6m": 201.53 },
  tf: {},
  reason: "No weekly setup · Monthly 2U",
  has_setup: false,
  setup: null,
  avg_dollar_volume: 506e6,
  atr: 8.98,
  atr_pct: 4.03,
  score: 89.9,
  score_breakdown: [],
} as unknown as ScanRow;

const render = (props: Partial<Parameters<typeof ScanTable>[0]> = {}) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <ScanTable rows={[row]} watchColumn={false} {...props} />
    </MemoryRouter>,
  );

describe("Stock Scanner keeps the scanning columns", () => {
  it("shows 1M / 3M / 6M, D · W · M and Weekly setup", () => {
    const html = render();
    expect(html).toContain("perf-col");
    expect(html).toContain("+161.3%");
    expect(html).toContain("D · W · M");
    expect(html).toContain("tf-badges");
    expect(html).toContain("Weekly setup");
    expect(html).toContain("setup-cell");
  });
});

describe("ListTable (Watchlist and Positions share it)", () => {
  const crossed = {
    TEAM: {
      premarket: null,
      ema5m: {
        price: 224,
        basis: "live" as const,
        time: "2026-10-22T19:50:00Z",
        bar_time: "2026-10-22T19:50:00Z",
        ema6: 223.5,
        ema20: 224.5,
        vs6: "above" as const,
        vs20: "below" as const,
        highlight: [6],
        highlight_bar: "2026-10-22T19:50:00Z",
        highlight_until: "2026-10-22T20:00:00Z",
      },
      ema5m_cross: "6",
      ema5m_cross_bar: "2026-10-22T19:50:00Z",
    },
  };
  const list = (extra = {}) =>
    renderToStaticMarkup(
      <MemoryRouter>
        <ListTable rows={[row]} watchColumn={false} intraday={crossed} {...extra} />
      </MemoryRouter>,
    );

  it("drops 1M / 3M / 6M, D · W · M and Weekly setup", () => {
    const html = list();
    expect(html).not.toContain("perf-col");
    expect(html).not.toContain("+161.3%");
    expect(html).not.toContain("D · W · M");
    expect(html).not.toContain("tf-badges");
    expect(html).not.toContain("Weekly setup");
    expect(html).not.toContain("setup-cell");
    expect(html).toContain("Atlassian Corporation");
  });

  it("adds the intraday columns after any page columns, and the crossover highlight", () => {
    const html = list({
      extraColumns: [{ key: "pnl", label: "$ P/L", sortValue: () => null, render: () => "x" }],
    });
    const order = ["$ P/L", "Premkt", "Day range", "6 EMA (5m)", "20 EMA (5m)"].map((label) => html.indexOf(`>${label}<`));
    expect(order.every((i) => i > -1)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toMatch(/<tr class="ema-cross" title="Crossed back above the 6 EMA \(5m\)/);
  });
});
