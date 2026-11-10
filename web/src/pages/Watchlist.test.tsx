import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { WatchSetupCell } from "./Watchlist";

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
