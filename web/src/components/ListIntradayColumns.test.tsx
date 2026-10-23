import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ListIntraday, ScanRow } from "../api";
import { crossHighlight, emaDistance, fmtVolume, rangeTone } from "../listIntraday";
import { listIntradayColumns } from "./ListIntradayColumns";

const row = { symbol: "TEAM" } as ScanRow;
const ema = {
  price: 226.9,
  basis: "premarket" as const,
  time: "2026-10-22T12:50:00Z",
  bar_time: "2026-10-21T19:55:00Z",
  ema6: 225.8697,
  ema20: 227.5,
  vs6: "above" as const,
  vs20: "below" as const,
  highlight: [] as number[],
  highlight_bar: null,
  highlight_until: null,
};
const info: ListIntraday = {
  premarket: {
    session: "2026-10-22",
    price: 226.9,
    time: "2026-10-22T12:50:00Z",
    source: "sip bar",
    prev_close: 225.505,
    change_pct: 0.62,
    volume: 134459,
    volume_through: "2026-10-22T12:55:00Z",
    final: false,
  },
  ema5m: ema,
  ema5m_cross: null,
  ema5m_cross_bar: null,
};
const html = (cols: ReturnType<typeof listIntradayColumns>, key: string) =>
  renderToStaticMarkup(<>{cols.find((c) => c.key === key)!.render(row)}</>);

describe("watchlist / positions intraday columns", () => {
  it("has compact headers in order: premarket, 6 EMA (5m), 20 EMA (5m)", () => {
    expect(listIntradayColumns({}).map((c) => c.label)).toEqual(["Premkt", "Day range", "6 EMA (5m)", "20 EMA (5m)"]);
  });

  it("shows the premarket print, % vs prior close and volume", () => {
    const out = html(listIntradayColumns({ TEAM: info }), "premarket");
    expect(out).toContain("226.90");
    expect(out).toContain('class="sub green-text">+0.62%');
    expect(out).toContain("vol 134K");
    expect(out).not.toContain("pm-tag");
  });

  it("tags the frozen premarket close after the open", () => {
    const final = { ...info, premarket: { ...info.premarket!, final: true } };
    expect(html(listIntradayColumns({ TEAM: final }), "premarket")).toContain('<span class="pm-tag">PM</span>');
  });

  it("renders green / red EMA pills", () => {
    const cols = listIntradayColumns({ TEAM: info });
    expect(html(cols, "ema6_5m")).toContain('class="ema-pill above"');
    expect(html(cols, "ema6_5m")).toContain(">Above<");
    expect(html(cols, "ema20_5m")).toContain('class="ema-pill below"');
  });

  it("shows a neutral dash when data is missing", () => {
    const cols = listIntradayColumns(undefined);
    for (const key of ["premarket", "day_range", "ema6_5m", "ema20_5m"]) {
      expect(html(cols, key)).toMatch(/<span class="muted"[^>]*>—<\/span>/);
    }
  });

  it("sorts EMA columns by distance from the EMA", () => {
    expect(emaDistance(ema, 6)).toBeCloseTo(0.457, 2);
    expect(emaDistance(null, 20)).toBeNull();
    expect(fmtVolume(2_511_636)).toBe("2.5M");
  });

  it("has no emoji", () => {
    const cols = listIntradayColumns({ TEAM: info });
    for (const c of cols) expect(html(cols, c.key)).not.toMatch(/\p{Extended_Pictographic}/u);
  });
});

describe("5-minute EMA crossover row highlight", () => {
  it("is off without a crossover", () => {
    expect(crossHighlight(info)).toBeNull();
    expect(crossHighlight(undefined)).toBeNull();
  });

  it("names the EMA crossed back above", () => {
    const crossed = {
      ...info,
      ema5m: { ...ema, highlight: [6], highlight_bar: "2026-10-22T17:20:00Z", highlight_until: "2026-10-22T17:30:00Z" },
    };
    const mark = crossHighlight(crossed)!;
    expect(mark.className).toBe("ema-cross");
    expect(mark.title).toContain("Crossed back above the 6 EMA (5m)");
    expect(crossHighlight({ ...crossed, ema5m: { ...crossed.ema5m, highlight: [6, 20] } })!.title).toContain(
      "6 EMA and 20 EMA",
    );
  });
});

describe("Day range column", () => {
  const withRange = (pct: number, basis: "regular" | "premarket" | "last session" = "regular") => ({
    TEAM: {
      ...info,
      day_range: { low: 220, high: 230, last: 220 + pct / 10, pct, basis, session: "2026-10-22" },
    },
  });

  it("places the marker at the last price and colors it by position", () => {
    const out = html(listIntradayColumns(withRange(85)), "day_range");
    expect(out).toContain('class="day-range near-high"');
    expect(out).toContain("left:85%");
    expect(out).toContain("85%");
    expect(out).toContain("low 220.00 · high 230.00 · last 228.50");
    expect(html(listIntradayColumns(withRange(12)), "day_range")).toContain("near-low");
    expect(html(listIntradayColumns(withRange(50)), "day_range")).toContain('class="day-range mid"');
  });

  it("tags the premarket range and names the basis in the tooltip", () => {
    const out = html(listIntradayColumns(withRange(40, "premarket")), "day_range");
    expect(out).toContain('<span class="pm-tag">PM</span>');
    expect(out).toContain("Premarket range so far");
    expect(html(listIntradayColumns(withRange(40, "last session")), "day_range")).toContain("Last session&#x27;s range");
  });

  it("thresholds", () => {
    expect(rangeTone(70)).toBe("near-high");
    expect(rangeTone(30)).toBe("near-low");
    expect(rangeTone(31)).toBe("mid");
  });
});
