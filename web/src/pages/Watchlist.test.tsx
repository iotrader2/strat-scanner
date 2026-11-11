import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WatchlistLoaded, WatchSetupCell } from "./Watchlist";

describe("WatchSetupCell", () => {
  it("shows the side and the setups, or a dash when the name does not qualify", () => {
    const html = renderToStaticMarkup(
      <WatchSetupCell
        setups={[
          { kind: "episodic-pivot", label: "Episodic Pivot", side: "long" },
          { kind: "ma-overcut-fail", label: "MA Overcut and Fail (10-day)", side: "short", period: 10 },
          { kind: "ma-overcut-fail", label: "MA Overcut and Fail (20-day)", side: "short", period: 20 },
        ]}
      />,
    );
    expect(html).toContain('class="side-chip long">LONG<');
    expect(html).toContain("EP");
    expect(html).toContain('class="side-chip short">SHORT<');
    expect(html).toContain("MA Overcut Fail 10/20");
    expect(html).not.toContain(">Trigger<");
    expect(html).not.toContain(">To trigger<");
    expect(renderToStaticMarkup(<WatchSetupCell setups={[]} />)).toContain(">—</span>");
  });
});

describe("WatchlistLoaded", () => {
  it("shows the post-close load in Phoenix time, and a dash when it has never run", () => {
    const html = renderToStaticMarkup(
      <WatchlistLoaded loadedAt="2026-11-10T21:01:00Z" updatedAt="2026-11-10T16:15:00Z" />,
    );
    expect(html).toContain("Last loaded: Tue Nov 10, 2:01 PM MST");
    expect(html).toContain("Last updated: Tue Nov 10, 9:15 AM MST");
    const empty = renderToStaticMarkup(<WatchlistLoaded loadedAt={null} updatedAt={null} />);
    expect(empty).toContain("Last loaded: —");
    expect(empty).toContain("Last updated: —");
  });
});
