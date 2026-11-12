import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { sample } from "../alerts.test";
import { DEFAULT_ALERT_FILTERS, alertDayStatus } from "../alerts";
import { AlertDayBanner, AlertFilterBar, AlertLiquidityFilters, AlertsTable, MetricsTable, RsPill } from "./Alerts";

describe("AlertsTable", () => {
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <AlertsTable
        alerts={[
          sample({
            id: 7, score: 91, rs: 0.934, industry: "Semiconductors", industry_rank: 3, industry_total: 120,
            details: { ...sample({}).details, daily_setups: ["Flat Base Breakout"] },
          }),
          sample({
            id: 8, symbol: "MU", setup: "240", top: false, acknowledged: true, status: "exited", filled: true, fill_price: 101.01,
            fill_at: "2026-10-23T13:40:00Z", exit_price: 103.25, exit_at: "2026-10-23T15:00:00Z", exit_reason: "close_under_ma",
            r_multiple: 2.0, high_reached: 103.9, score: null,
          }),
        ]}
        flashing={new Set([7])}
        onAck={() => undefined}
        onBought={() => undefined}
      />
    </MemoryRouter>,
  );

  it("has the spec columns, with Score after Ticker and Bought before Acknowledge", () => {
    for (const h of ["Watch", "Ticker", "Score", "RS", "Side", "Daily setup", "Industry", "Entry", "EMA", "Trigger", "Stop", "Stop %", "Risk / sh", "Status"]) expect(html).toContain(`>${h}</th>`);
    expect(html).toContain('class="sortable');
    expect(html).not.toContain("▼");
    expect(html).not.toContain("▲");
    const head = html.slice(html.indexOf("<thead>"), html.indexOf("</thead>"));
    const labels = [...head.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map((m) => m[1].replace(/<[^>]+>/g, "").trim());
    expect(labels.slice(labels.indexOf("Ticker"), labels.indexOf("Trigger") + 1)).toEqual([
      "Ticker", "Score", "RS", "Side", "Daily setup", "Industry", "Entry", "EMA", "Trigger",
    ]);
    const bought = labels.indexOf("");
    expect(head).toContain('aria-label="Bought"');
    expect(labels.indexOf("What happened")).toBeLessThan(bought);
    expect(html).toContain("Bought →");
    expect(html).toContain('class="bought-col"');
    expect(html).not.toMatch(/class="[^"]*bought-col[^"]*actions-col/);
  });

  it("shows the side in its own column and the open R of a triggered trade", () => {
    const view = renderToStaticMarkup(
      <MemoryRouter>
        <AlertsTable
          alerts={[
            sample({ id: 1, status: "triggered", filled: true, fill_price: 101.01, open_r: 1.234, price: 102.4 }),
            sample({ id: 2, symbol: "MU", setup: "s240", status: "triggered", filled: true, fill_price: 99.0, open_r: -0.5 }),
          ]}
          flashing={new Set()}
          onAck={() => undefined}
          onBought={() => undefined}
        />
      </MemoryRouter>,
    );
    expect(view).toContain('class="side-chip long">LONG<');
    expect(view).toContain('class="side-chip short">SHORT<');
    expect(view).toContain(">+1.23R<");
    expect(view).toContain(">-0.50R<");
    expect(view).toContain('title="At 102.40"');
  });

  it("shows RS, the daily setup and the industry with its rank", () => {
    expect(html).toContain('<span class="score-pill hi">P93</span>');
    expect(html).toContain('<td class="daily-setup-cell">Flat Base Breakout</td>');
    expect(html).toContain(">Semiconductors<");
    expect(html).toContain(">#3/120<");
  });

  it("shows the scanner score pill, or a dash when the name has no score", () => {
    expect(html).toContain('class="score-pill hi');
    expect(html).toContain(">91<");
    expect(html).toContain('<td class="num"><span class="muted">—</span></td>');
  });

  it("puts the logo left of the ticker and tags top names", () => {
    expect(html).toMatch(/class="sym sym-with-logo"[^>]*><span class="ticker-logo[^"]*"[\s\S]*?<\/span>AAPL<span class="top-chip">TOP<\/span>/);
  });

  it("shows the earnings warning only when the row carries one", () => {
    expect(html).not.toContain("earnings-icon");
    const warned = renderToStaticMarkup(
      <MemoryRouter>
        <AlertsTable
          alerts={[sample({ earnings: { date: "2026-10-29", date_end: null, timing: "AMC", days_until: 3 } })]}
          flashing={new Set()}
          onAck={() => undefined}
          onBought={() => undefined}
        />
      </MemoryRouter>,
    );
    expect(warned).toContain('class="earnings-icon"');
    expect(warned).toContain("Earnings Thu, Oct 29");
    expect(warned).toContain("in 3 days");
  });

  it("flashes new unread rows and offers acknowledge", () => {
    expect(html).toContain('class="alert-row unread flash"');
    expect(html).toContain(">Acknowledge</span>");
    expect(html).toContain(">Ack</span>");
    expect(html).toContain('class="alert-row read "');
  });

  it("shows levels, status and outcome", () => {
    expect(html).toContain(">101.01<");
    expect(html).toContain(">99.89<");
    expect(html).toContain(">1.12<");
    expect(html).toContain(">Watch<");
    expect(html).toContain("Watching: trigger over 101.00 (last 15-min high)");
    expect(html).toContain("+2.00R");
    expect(html).toContain("out 103.25 at 8:00 AM (close under 240 EMA)");
  });

  it("names the EMA with its chart color and shows its level on the touch", () => {
    expect(html).toContain("Pullback to rising 120 EMA");
    expect(html).toContain("Pullback to rising 240 EMA");
    expect(html).toContain('class="ema-dot" style="background:#ef4444"');
    expect(html).toContain('class="ema-dot" style="background:#facc15"');
    expect(html).toContain(">99.12<");
    expect(html).toContain("On the touch candle: 120 EMA 99.12, 240 EMA 97.50, rising 0.05% over the check");
  });

  it("shows the trigger rule when hovering the setup", () => {
    expect(html).toContain("pulls back from above to the rising 120 EMA on the 15-minute chart and holds it");
    expect(html).toContain("the trigger is the previous 15-minute candle&#x27;s high + 1c");
  });

  it("uses no emoji", () => {
    expect(/\p{Extended_Pictographic}/u.test(html)).toBe(false);
  });

  it("keeps the same columns in history and drops the write actions", () => {
    const archived = renderToStaticMarkup(
      <MemoryRouter>
        <AlertsTable
          alerts={[sample({ id: 7 })]}
          flashing={new Set()}
          onAck={() => undefined}
          onBought={() => undefined}
          readOnly
        />
      </MemoryRouter>,
    );
    for (const h of ["Watch", "Ticker", "Score", "RS", "Side", "Daily setup", "Industry", "Entry", "Trigger", "Open R", "Stop", "Status", "What happened"]) {
      expect(archived).toContain(`>${h}</th>`);
    }
    expect(archived).toContain('aria-label="Bought"');
    expect(archived).not.toContain("Bought →");
    expect(archived).not.toContain(">Acknowledge</span>");
  });
});

describe("MetricsTable", () => {
  it("lists daily setups with a side, and counts All once", () => {
    const html = renderToStaticMarkup(
      <MetricsTable
        rows={[
          { setup: "episodic-pivot", name: "Episodic Pivot", side: "long", count: 2, filled: 1, closed: 1, open: 0, fill_rate: 50, win_rate: 100, avg_r: 1.5, total_r: 1.5 },
          { setup: "ma-overcut-fail:10", name: "MA Overcut and Fail (10-day)", side: "short", count: 1, filled: 1, closed: 1, open: 0, fill_rate: 100, win_rate: 0, avg_r: -1, total_r: -1 },
          { setup: "unknown", name: "Unknown", side: null, count: 1, filled: 0, closed: 0, open: 0, fill_rate: 0, win_rate: null, avg_r: null, total_r: null },
          { setup: "All", name: "All setups", side: null, count: 3, filled: 2, closed: 2, open: 0, fill_rate: 66.7, win_rate: 50, avg_r: 0.25, total_r: 0.5 },
        ]}
      />,
    );
    expect(html).toContain(">Daily setup</th>");
    expect(html).toContain("Episodic Pivot");
    expect(html).toContain('class="side-chip long">LONG<');
    expect(html).toContain("MA Overcut and Fail (10-day)");
    expect(html).toContain('class="side-chip short">SHORT<');
    expect(html).toContain(">Unknown<");
    expect(html).toContain('class="total-row"');
    expect(html).toContain("All setups");
    expect(html).not.toContain("ema-dot");
    expect(html).not.toContain("Metrics by EMA");
  });
});

describe("Alert day window", () => {
  it("shows each EMA chip watching during the session", () => {
    const html = renderToStaticMarkup(<AlertDayBanner status={alertDayStatus(new Date("2026-10-23T15:00:00Z"))} />);
    expect(html).toContain('role="status"');
    expect(html).toContain("Watching for pullbacks until 9:00 AM Phoenix.");
    expect(html).toContain('class="alert-window-chip open"');
    for (const p of ["120", "240", "480"]) expect(html).toContain(`${p} EMA`);
    expect(/\p{Extended_Pictographic}/u.test(html)).toBe(false);
  });

  it("says the day is finished after the noon ET cutoff", () => {
    const html = renderToStaticMarkup(<AlertDayBanner status={alertDayStatus(new Date("2026-10-23T16:01:00Z"))} />);
    expect(html).toContain('class="alert-day done"');
    expect(html).toContain("Alerts are done for the day.");
    expect(html).toContain("The session was 6:45–9:00 AM Phoenix.");
  });
});


describe("AlertFilterBar", () => {
  const bar = (filters = DEFAULT_ALERT_FILTERS, ticker = "") =>
    renderToStaticMarkup(
      <AlertFilterBar filters={filters} onChange={() => undefined} ticker={ticker} onTicker={() => undefined} shown={3} total={9} />,
    );

  it("has the ticker search, side buttons and the score / RS sliders", () => {
    const html = bar();
    expect(html).toContain('id="alert-ticker-search"');
    for (const b of [">All<", ">Long<", ">Short<"]) expect(html).toContain(b);
    expect(html).toContain('aria-label="Status"');
    for (const b of [">Watch<", ">Triggered<", ">Stopped<", ">Break-even<", ">Exited<", ">Expired<", ">Cancelled<"]) {
      expect(html).toContain(b);
    }
    expect(html.match(/>All</g)?.length).toBe(2); // one All per button group
    expect(html).toContain('aria-label="Min Score"');
    expect(html).toContain('aria-label="Max RS"');
    expect(html).toContain(">9 alerts<");
    expect(html).not.toContain("Clear filters");
  });

  it("shows the count and a clear button once something filters", () => {
    expect(bar({ ...DEFAULT_ALERT_FILTERS, side: "short" })).toContain(">3 of 9 shown<");
    expect(bar(DEFAULT_ALERT_FILTERS, "MU")).toContain("Clear filters");
    expect(bar({ ...DEFAULT_ALERT_FILTERS, rs: [10, 90] })).toContain("P10 – P90");
  });
});

describe("RsPill", () => {
  it("colours RS like the score pill", () => {
    expect(renderToStaticMarkup(<RsPill rs={0.12} />)).toBe('<span class="score-pill lo">P12</span>');
    expect(renderToStaticMarkup(<RsPill rs={null} />)).toContain("—");
  });
});

describe("Alert liquidity sliders", () => {
  it("matches the scanner volume and ATR sliders, and exempts names you added", () => {
    const html = renderToStaticMarkup(
      <AlertLiquidityFilters volume={100_000_000} atr={[0, 12]} onVolume={() => undefined} onAtr={() => undefined} />,
    );
    expect(html).toContain("Min avg $ volume");
    expect(html).toContain("≥ $100M");
    expect(html).toContain("$10M");
    expect(html).toContain("$5B");
    expect(html).toContain("ATR %");
    expect(html).toContain(">Any<");
    expect(html).toContain("0%");
    expect(html).toContain("12%+");
    expect(html).toContain("needs an ATR above 3% to be added or to");
    expect(html).toContain("the sliders do not apply to names you added.");
  });
});
