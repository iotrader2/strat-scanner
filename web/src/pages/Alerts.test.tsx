import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { alertDayStatus } from "../alerts";
import { sample } from "../alerts.test";
import { AlertDayBanner, AlertsTable } from "./Alerts";

describe("AlertsTable", () => {
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <AlertsTable
        alerts={[
          sample({ id: 7, score: 91 }),
          sample({
            id: 8, symbol: "MU", setup: "D", top: false, acknowledged: true, status: "exited", filled: true, fill_price: 101.01,
            fill_at: "2026-10-23T13:40:00Z", exit_price: 103.25, exit_at: "2026-10-23T15:00:00Z", exit_reason: "close_under_20ema",
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
    for (const h of ["Fired", "Ticker", "Score", "Setup", "Trigger", "Stop", "Stop %", "Risk / sh", "Status"]) expect(html).toContain(`>${h}</th>`);
    const head = html.slice(html.indexOf("<thead>"), html.indexOf("</thead>"));
    const labels = [...head.matchAll(/<th\b[^>]*>([\s\S]*?)<\/th>/g)].map((m) => m[1].replace(/<[^>]+>/g, "").trim());
    expect(labels.slice(labels.indexOf("Ticker"), labels.indexOf("Setup") + 1)).toEqual(["Ticker", "Score", "Setup"]);
    const bought = labels.indexOf("");
    expect(head).toContain('aria-label="Bought"');
    expect(labels.indexOf("What happened")).toBeLessThan(bought);
    expect(html).toContain("Bought →");
    expect(html).toContain('class="bought-col"');
    expect(html).not.toMatch(/class="[^"]*bought-col[^"]*actions-col/);
  });

  it("shows the scanner score pill, or a dash when the name has no score", () => {
    expect(html).toContain('class="score-pill hi');
    expect(html).toContain(">91<");
    expect(html).toContain('<td class="num"><span class="muted">—</span></td>');
  });

  it("puts the logo left of the ticker and tags top names", () => {
    expect(html).toMatch(/class="sym sym-with-logo"[^>]*><span class="ticker-logo[^"]*"[\s\S]*?<\/span>AAPL<span class="top-chip">TOP<\/span>/);
  });

  it("flashes new unread rows and offers acknowledge", () => {
    expect(html).toContain('class="alert-row unread flash"');
    expect(html).toContain(">Acknowledge</button>");
    expect(html).toContain('class="alert-row read "');
  });

  it("shows levels, status and outcome", () => {
    expect(html).toContain(">101.01<");
    expect(html).toContain(">99.89<");
    expect(html).toContain(">1.12<");
    expect(html).toContain(">Pending<");
    expect(html).toContain("+2.00R");
    expect(html).toContain("out 103.25 at 8:00 AM (close under 20 EMA)");
  });

  it("shows the trigger rule when hovering the setup", () => {
    expect(html).toContain('title="Opening bar closes in the top 30% and over the 6 and 20 EMAs."');
    expect(html).toContain('title="After a pullback to the rising 20 EMA, a green bar closes back over the 6."');
  });

  it("uses no emoji", () => {
    expect(/\p{Extended_Pictographic}/u.test(html)).toBe(false);
  });
});

describe("Alert day window", () => {
  it("shows the midday window still open and the morning setups finished", () => {
    const html = renderToStaticMarkup(<AlertDayBanner status={alertDayStatus(new Date("2026-10-23T15:10:00Z"))} />);
    expect(html).toContain('role="status"');
    expect(html).toContain("F can fire 8:35 AM – 1:00 PM Phoenix.");
    expect(html).toContain("Alerts finish at 1:00 PM Phoenix.");
    expect(html).toContain('class="alert-window-chip done"');
    expect(html).toContain(">done<");
    expect(html).toContain('class="alert-window-chip later"');
    expect(html).not.toContain("weakening");
    expect(/\p{Extended_Pictographic}/u.test(html)).toBe(false);
  });

  it("says the day is finished after the last window", () => {
    const html = renderToStaticMarkup(<AlertDayBanner status={alertDayStatus(new Date("2026-10-23T20:01:00Z"))} />);
    expect(html).toContain('class="alert-day done"');
    expect(html).toContain("Alerts are done for the day.");
    expect(html).toContain("The window was 6:35 AM – 1:00 PM Phoenix.");
    expect(html).not.toContain(">done<");
  });
});
