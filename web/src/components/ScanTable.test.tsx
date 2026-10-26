import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { ScanRow } from "../api";
import { ListTable } from "./ListTable";
import { ScanTable } from "./ScanTable";

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "../styles.css"), "utf8");

/** Visible header labels, in order, without the sort arrow. */
function headerLabels(html: string): string[] {
  const head = html.slice(html.indexOf("<thead>"), html.indexOf("</thead>"));
  return [...head.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map((m) =>
    m[1]
      .replace(/<[^>]+>/g, "")
      .replace(/&nbsp;|&#xA0;|\u00a0/g, " ")
      .replace(/[▲▼]/g, "")
      .trim(),
  );
}

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
    expect(html.match(/>Day</g)).toHaveLength(1);
    expect(html).toContain('<span class="red-text">-1.04%</span>');
  });

  it("adds the intraday columns after any page columns, and the crossover highlight", () => {
    const html = list({
      extraColumns: [{ key: "pnl", label: "$ P/L", sortValue: () => null, render: () => "x" }],
    });
    const order = ["$ P/L", "Premkt", "Day", "Day range", "6 EMA (5m)", "20 EMA (5m)", "Trigger"].map((label) => html.indexOf(`>${label}<`));
    expect(order.every((i) => i > -1)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toMatch(/<tr class="ema-cross" title="Crossed back above the 6 EMA \(5m\)/);
  });

  it("puts Score immediately right of Price on both trading lists, once", () => {
    const watch = list();
    const watchHeads = headerLabels(watch).filter(Boolean);
    const price = watchHeads.indexOf("Price");
    expect(watchHeads[price + 1]).toBe("Score");
    expect(watchHeads[price + 2]).toBe("Premkt");
    expect(watchHeads.filter((h) => h === "Score")).toHaveLength(1);
    expect(watch.match(/score-pill/g)).toHaveLength(1);
    expect(watch).not.toContain("score-col");

    const positions = list({
      priceLabel: "Last",
      leadColumns: [{ key: "entry_price", label: "Buy price", sortValue: () => 100, render: () => "100.00" }],
      extraColumns: [
        { key: "gain_pct", label: "% G/L", sortValue: () => 1, render: () => "+1%" },
        { key: "pnl", label: "$ P/L", sortValue: () => 1, render: () => "x" },
        { key: "days_held", label: "Days held", sortValue: () => 3, render: () => "3d" },
      ],
    });
    const posHeads = headerLabels(positions).filter(Boolean);
    expect(posHeads.slice(posHeads.indexOf("Buy price"), posHeads.indexOf("Premkt") + 1)).toEqual([
      "Buy price",
      "Last",
      "Score",
      "% G/L",
      "$ P/L",
      "Days held",
      "Premkt",
    ]);
    expect(posHeads.filter((h) => h === "Score")).toHaveLength(1);
    expect(positions.match(/score-pill/g)).toHaveLength(1);
    expect(positions).not.toContain("score-col");
  });
});

describe("Price distance from the 6 / 20 / 50 SMA on every table", () => {
  const withMa = { ...row, ma_dist_pct: { "6": 2.42, "20": -0.2, "50": null } } as unknown as ScanRow;
  const labels = ["vs 6 MA", "vs 20 MA", "vs 50 MA"];
  const cells = (html: string) => [...html.matchAll(/<td class="num ma-dist-col ([a-z-]+)"[^>]*>([^<]*)<\/td>/g)].map((m) => [m[1], m[2]]);

  it("scanner: three sortable columns right after ATR %, signed percent, colored, em dash when missing", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ScanTable rows={[withMa]} watchColumn={false} />
      </MemoryRouter>,
    );
    const order = ["ATR %", ...labels].map((label) => html.indexOf(`>${label}<`));
    expect(order.every((i) => i > -1)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toContain('title="Percent distance of price from the daily 20 SMA; 0% = on the average"');
    expect(html).toMatch(/class="sortable num ma-dist-col /);
    expect(cells(html)).toEqual([
      ["green-text", "+2.4%"],
      ["red-text", "-0.2%"],
      ["muted", "—"],
    ]);
  });

  it("keeps Score at the end of the scanner, once", () => {
    const html = render();
    const heads = headerLabels(html).filter(Boolean);
    expect(heads[heads.indexOf("Price") + 1]).not.toBe("Score");
    expect(heads.at(-1)).toBe("Score");
    expect(heads.filter((h) => h === "Score")).toHaveLength(1);
    expect(html).toContain("score-col");
  });

  it("watchlist / positions: right after 20 EMA (5m), once", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ListTable rows={[withMa]} watchColumn={false} intraday={{}} />
      </MemoryRouter>,
    );
    const order = ["20 EMA (5m)", ...labels, "Trigger"].map((label) => html.indexOf(`>${label}<`));
    expect(order.every((i) => i > -1)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    for (const label of labels) expect(html.split(`>${label}<`)).toHaveLength(2);
    expect(html).toContain('<span class="green-text" title="Percent distance of price from the daily 6 SMA; 0% = on the average">+2.4%</span>');
    expect(html).toContain(">-0.2%</span>");
  });

  it("sorts by distance with missing values last", async () => {
    const { sortRows } = await import("./ScanTable");
    const a = { ...row, symbol: "A", ma_dist_pct: { "6": 2 } } as unknown as ScanRow;
    const b = { ...row, symbol: "B", ma_dist_pct: { "6": -1 } } as unknown as ScanRow;
    const c = { ...row, symbol: "C", ma_dist_pct: null } as unknown as ScanRow;
    expect(sortRows([c, b, a], "ma_dist_6", -1).map((r) => r.symbol)).toEqual(["A", "B", "C"]);
    expect(sortRows([c, a, b], "ma_dist_6", 1).map((r) => r.symbol)).toEqual(["B", "A", "C"]);
  });
});

describe("Bought column is not anchored", () => {
  it("the watchlist Bought cell scrolls with the row", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ListTable
          rows={[row]}
          watchColumn={false}
          intraday={{}}
          actionsLabel=""
          pinActions={false}
          actions={() => "Bought →"}
        />
      </MemoryRouter>,
    );
    expect(html).toContain("Bought →");
    expect(html).toContain('class="actions-col actions-flow"');
    expect(html).not.toMatch(/class="actions-col"/);
    const flow = css.slice(css.indexOf("td.actions-col.actions-flow"));
    expect(flow).toMatch(/td\.actions-col\.actions-flow \{ position: static;/);
    expect(css).not.toMatch(/actions-flow[^}]*position:\s*sticky/);
  });

  it("positions has no Bought column; its row menu stays pinned", () => {
    const html = renderToStaticMarkup(
      <MemoryRouter>
        <ListTable rows={[row]} watchColumn={false} intraday={{}} actionsLabel="" actions={() => "⋯"} />
      </MemoryRouter>,
    );
    expect(html).not.toContain("Bought");
    expect(html).toContain('class="actions-col"');
    expect(html).not.toContain("actions-flow");
    expect(css).toMatch(/\.scan-table th\.actions-col, \.scan-table td\.actions-col \{\s*position: sticky; right: 0;/);
  });
});
