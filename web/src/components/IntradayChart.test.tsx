// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IntradayBar } from "../api";
import { VOLUME_UP_COLOR } from "../macd";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

interface Series {
  kind: string;
  options: { color?: string; priceScaleId?: string };
  data: { time: number; value?: number; close?: number; color?: string }[] | null;
}

const charts: {
  series: Series[];
  range: { from: number; to: number } | null;
  removed: boolean;
}[] = [];

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "candles",
  HistogramSeries: "volume",
  LineSeries: "line",
  ColorType: { Solid: "solid" },
  CrosshairMode: { Normal: 0 },
  TickMarkType: { Year: 0, Month: 1, DayOfMonth: 2, Time: 3, TimeWithSeconds: 4 },
  createChart: () => {
    const series: Series[] = [];
    const chart = {
      series,
      range: null as { from: number; to: number } | null,
      removed: false,
      addSeries: (kind: string, options: Series["options"]) => {
        const entry: Series = { kind, options, data: null };
        series.push(entry);
        return { setData: (data: Series["data"]) => { entry.data = data; } };
      },
      priceScale: () => ({ applyOptions: () => {} }),
      timeScale: () => ({
        setVisibleLogicalRange: (range: { from: number; to: number }) => {
          chart.range = range;
        },
      }),
      remove: () => {
        chart.removed = true;
      },
    };
    charts.push(chart);
    return chart;
  },
}));

const { IntradayChart } = await import("./IntradayChart");

const bars: IntradayBar[] = [10, 11, 12, 13, 14, 15].map((close, i) => ({
  time: 1_700_000_000 + i * 300,
  open: close - 0.5,
  high: close + 0.5,
  low: close - 1,
  close,
  volume: 5000 + i,
  ema: { "6": close - 0.2, "20": close - 0.5, "50": close - 1, "120": 100 + i },
}));

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  charts.length = 0;
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe("IntradayChart", () => {
  it("draws candles, volume, and a legend swatch for each EMA", async () => {
    await act(async () => {
      root.render(<IntradayChart bars={bars} visibleBars={3} displaySessions={5} seedSessions={30} />);
    });

    const html = host.innerHTML;
    expect(html).toContain("EMA");
    for (const period of [6, 20, 50, 120]) expect(html).toContain(`>${period}<`);
    // jsdom serializes hex backgrounds as rgb().
    expect(html).toContain("rgb(244, 114, 182)");
    expect(html).toContain("rgb(56, 189, 248)");
    expect(html).toContain("rgb(192, 132, 252)");
    expect(html).toContain("rgb(251, 191, 36)");
    expect(html).toContain("Premarket is excluded");
    expect(html).toContain("30 sessions");

    expect(charts).toHaveLength(1);
    const chart = charts[0];
    const candles = chart.series.find((series) => series.kind === "candles");
    const volume = chart.series.find((series) => series.kind === "volume");
    const lines = chart.series.filter((series) => series.kind === "line");
    expect(candles?.data).toHaveLength(bars.length);
    expect(volume?.options.priceScaleId).toBe("vol");
    expect(volume?.data).toHaveLength(bars.length);
    expect(volume?.data?.[0].color).toBe(VOLUME_UP_COLOR);
    expect(lines.map((line) => line.options.color)).toEqual(["#f472b6", "#38bdf8", "#c084fc", "#fbbf24"]);
    // The 120 line is the server's values, not a fresh EMA of the candles on screen.
    expect(lines[3].data?.map((point) => point.value)).toEqual([100, 101, 102, 103, 104, 105]);
    // Three bars on screen, the rest a scroll away.
    expect(chart.range?.from).toBe(bars.length - 3 - 0.5);
  });

  it("says when there is nothing to draw", async () => {
    await act(async () => {
      root.render(<IntradayChart bars={[]} />);
    });
    expect(host.textContent).toContain("No 15-minute bars");
    expect(charts).toHaveLength(0);
  });
});
