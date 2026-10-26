import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { sample } from "../alerts.test";
import { AlertsTable } from "./Alerts";

describe("AlertsTable", () => {
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <AlertsTable
        alerts={[
          sample({ id: 7 }),
          sample({
            id: 8, symbol: "MU", setup: "D", top: false, acknowledged: true, status: "exited", filled: true, fill_price: 101.01,
            fill_at: "2026-10-23T13:40:00Z", exit_price: 103.25, exit_at: "2026-10-23T15:00:00Z", exit_reason: "close_under_20ema",
            r_multiple: 2.0, high_reached: 103.9,
          }),
        ]}
        flashing={new Set([7])}
        onAck={() => undefined}
      />
    </MemoryRouter>,
  );

  it("has the spec columns", () => {
    for (const h of ["Fired", "Ticker", "Setup", "Trigger", "Stop", "Stop %", "Risk / sh", "Status"]) expect(html).toContain(`>${h}</th>`);
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

  it("uses no emoji", () => {
    expect(/\p{Extended_Pictographic}/u.test(html)).toBe(false);
  });
});
