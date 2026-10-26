// @vitest-environment jsdom
import { act } from "react";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChartCandle, IntradayChartData, ScanRow, Tf } from "../api";
import { DETAIL_TF_KEY } from "../persist";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { symbolMock, bars5mMock } = vi.hoisted(() => ({
  symbolMock: vi.fn(),
  bars5mMock: vi.fn(),
}));

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, api: { ...actual.api, symbol: symbolMock, bars5m: bars5mMock } };
});

vi.mock("../components/Watch", () => ({
  WatchButton: () => null,
}));

vi.mock("../components/CandleChart", () => ({
  CandleChart: ({ candles }: { candles: { time: string }[] }) =>
    createElement("div", { "data-chart": "candles", "data-times": candles.map((c) => c.time).join(",") }, "SMA 6 20 50"),
}));

vi.mock("../components/IntradayChart", () => ({
  IntradayChart: ({ bars }: { bars: unknown[] }) =>
    createElement("div", { "data-chart": "intraday" }, `EMA 5 20 50 360 · ${bars.length} bars`),
}));

const { default: Detail } = await import("./Detail");

function tfState() {
  return {
    tf: "D" as Tf,
    strat: "2U" as const,
    prev_strat: "1" as const,
    color: "green" as const,
    open: 200,
    high: 210,
    low: 198,
    close: 208,
    inside: false,
    hammer: false,
  };
}

function row(trigger: Tf | null): ScanRow {
  return {
    symbol: "AAPL",
    name: "Apple",
    sector: "Technology",
    sector_etf: "XLK",
    perf: { "1m": 1, "3m": 2, "6m": 3 },
    rs: 0.8,
    leader_status: "leader",
    is_leader: true,
    leadership: {
      rs: 0.8,
      status: "leader",
      excess: { "1m": 0, "3m": 0, "6m": 0 },
      above_ma: { "10": true, "20": true, "50": true },
      off_52w_high_pct: 1,
      off_6m_high_pct: 1,
      breakdown: "none",
      breakdown_reasons: [],
    },
    tightness: null,
    kill_candle: null,
    breakout: null,
    kind: "stock",
    indexes: "",
    in_universe: true,
    price: 210,
    change_pct: 0.4,
    avg_dollar_volume: 1e9,
    avg_volume: 5e6,
    as_of: "2026-10-22",
    score: 80,
    score_raw: 8,
    score_max_raw: 10,
    score_breakdown: [],
    full_continuity: false,
    mw_green: true,
    monthly_2u: false,
    has_setup: false,
    trigger: 212,
    trigger_tf: trigger,
    setup: null,
    triggered: false,
    trigger_distance_pct: 1,
    nearest_trigger: null,
    nearest_trigger_label: null,
    nearest_trigger_distance_pct: null,
    reason: "Monthly 2U",
    tf: { D: { ...tfState(), tf: "D" }, W: { ...tfState(), tf: "W" }, M: { ...tfState(), tf: "M" } },
    setups: [],
  };
}

const daily: ChartCandle = {
  time: "2026-10-22",
  open: 200,
  high: 212,
  low: 198,
  close: 210,
  volume: 1000,
  strat: "2U",
  hammer: false,
};

const intraday: IntradayChartData = {
  symbol: "AAPL",
  session: "regular",
  bar_minutes: 5,
  time_zone: "America/New_York",
  display_sessions: 5,
  seed_sessions: 30,
  sessions: 5,
  bars: [
    { time: 1_700_000_000, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10, ema: { "5": 1.4, "20": 1.2, "50": 1.1, "360": 1 } },
  ],
};

function page(version: string | null = null) {
  return createElement(
    MemoryRouter,
    { initialEntries: ["/stock/AAPL"] },
    createElement(
      Routes,
      null,
      createElement(Route, { path: "/stock/:symbol", element: createElement(Detail, { version }) }),
    ),
  );
}

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  localStorage.clear();
  symbolMock.mockReset();
  bars5mMock.mockReset();
  bars5mMock.mockResolvedValue(intraday);
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function labels(): string[] {
  return [...host.querySelectorAll(".seg button")].map((button) => button.textContent ?? "");
}

function activeLabel(): string | undefined {
  return host.querySelector(".seg button.active")?.textContent ?? undefined;
}

async function renderLoaded(trigger: Tf | null) {
  symbolMock.mockResolvedValue({ row: row(trigger), charts: { D: [daily], W: [daily], M: [daily] } });
  await act(async () => {
    root.render(page());
  });
  await act(async () => {
    await Promise.resolve();
  });
}

describe("detail chart switcher", () => {
  it("shows one chart and does not fetch 5-minute bars until 5min is selected", async () => {
    await renderLoaded("D");

    expect(labels()).toEqual(["5min", "Daily", "Weekly", "Monthly"]);
    expect(activeLabel()).toBe("Daily");
    expect(host.querySelector("[data-chart='candles']")).not.toBeNull();
    expect(host.querySelector("[data-chart='intraday']")).toBeNull();
    expect(host.textContent).toContain("SMA 6 20 50");
    expect(host.textContent).toContain("H = hammer");
    expect(bars5mMock).not.toHaveBeenCalled();
    expect(symbolMock).toHaveBeenCalledWith("AAPL");

    await act(async () => {
      host.querySelectorAll<HTMLButtonElement>(".seg button")[0].click();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(activeLabel()).toBe("5min");
    expect(bars5mMock).toHaveBeenCalledTimes(1);
    expect(bars5mMock).toHaveBeenCalledWith("AAPL");
    expect(host.querySelector("[data-chart='intraday']")).not.toBeNull();
    expect(host.querySelector("[data-chart='candles']")).toBeNull();
    expect(host.textContent).toContain("EMA 5 20 50 360");
    expect(host.textContent).not.toContain("H = hammer");

    await act(async () => {
      host.querySelectorAll<HTMLButtonElement>(".seg button")[1].click();
    });
    expect(activeLabel()).toBe("Daily");
    expect(host.querySelector("[data-chart='candles']")).not.toBeNull();
    expect(host.querySelector("[data-chart='intraday']")).toBeNull();
    expect(bars5mMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(`strat:${DETAIL_TF_KEY}`)).toBe(JSON.stringify("D"));
  });

  it("keeps Weekly when the row has no trigger timeframe, still without a 5-minute fetch", async () => {
    await renderLoaded(null);
    expect(activeLabel()).toBe("Weekly");
    expect(host.querySelector("[data-chart='candles']")?.getAttribute("data-times")).toBe("2026-10-22");
    expect(bars5mMock).not.toHaveBeenCalled();
  });

  it("fetches 5-minute bars on load only when that view was saved", async () => {
    localStorage.setItem(`strat:${DETAIL_TF_KEY}`, JSON.stringify("5m"));
    await renderLoaded("W");
    expect(activeLabel()).toBe("5min");
    expect(bars5mMock).toHaveBeenCalledTimes(1);
    expect(host.querySelector("[data-chart='intraday']")).not.toBeNull();
    expect(host.querySelector("[data-chart='candles']")).toBeNull();
  });
});
