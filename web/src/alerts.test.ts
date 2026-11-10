import { describe, expect, it } from "vitest";
import type { TradeAlert } from "./api";
import {
  DEFAULT_ALERT_FILTERS,
  alertFiltersActive,
  filterAlerts,
  normalizeAlertFilters,
  rsLevel,
  SETTING_GROUPS,
  SETUP_NAMES,
  alertSortValue,
  dailySetupText,
  sortByColumn,
  toggleColumnSort,
  isShortSetup,
  setupPeriod,
  STATUS_LABEL,
  alertDayStatus,
  fmtR,
  freshAlerts,
  maText,
  notificationText,
  phoenixTime,
  playChime,
  riskPerShare,
  statusTone,
  stopPct,
  todayEmptyLead,
  triggeredAlerts,
} from "./alerts";

export const sample = (over: Partial<TradeAlert> = {}): TradeAlert => ({
  id: 1,
  symbol: "AAPL",
  session: "2026-10-23",
  setup: "120",
  setup_bar: "2026-10-23T13:30:00Z",
  fired_at: "2026-10-23T13:35:00Z",
  detected_at: "2026-10-23T13:36:00Z",
  late: false,
  top: true,
  trigger_price: 101.01,
  stop_price: 99.89,
  setup_low: 99.9,
  setup_high: 101,
  ref_price: 100.9,
  status: "pending",
  filled: false,
  fill_price: null,
  fill_at: null,
  high_reached: null,
  stop_hit: false,
  breakeven_at: null,
  exit_price: null,
  exit_at: null,
  exit_reason: null,
  r_multiple: null,
  details: { ma: 99.1234, ma_slope_pct: 0.0512, touched: [120], ma_values: { "120": 99.1234, "240": 97.5, "480": null } },
  acknowledged: false,
  score: null,
  ...over,
});

describe("alert day", () => {
  const at = (iso: string, settings?: Record<string, number>) => alertDayStatus(new Date(iso), settings);

  it("runs from the first 15-minute close to the bell, in Phoenix time all year", () => {
    const summer = at("2026-10-23T13:00:00Z");
    expect(summer.phase).toBe("before");
    expect(summer.headline).toBe("Alerts start at 6:45 AM Phoenix.");
    expect(summer.detail).toBe("Session 6:45 AM – 1:00 PM Phoenix.");
    expect(summer.windows.map((w) => w.setup)).toEqual(["120", "240", "480"]);
    expect(summer.windows.every((w) => w.state === "later")).toBe(true);

    const winter = at("2026-11-02T14:00:00Z");
    expect(winter.headline).toBe("Alerts start at 7:45 AM Phoenix.");
  });

  it("is open during the session and done after it", () => {
    const mid = at("2026-10-23T16:00:00Z");
    expect(mid.phase).toBe("open");
    expect(mid.headline).toBe("Watching for pullbacks until 1:00 PM Phoenix.");
    expect(mid.windows.every((w) => w.state === "open")).toBe(true);
    const done = at("2026-10-23T20:01:00Z");
    expect(done.phase).toBe("done");
    expect(todayEmptyLead(done)).toBe("Alerts are done for the day. The session was 6:45 AM – 1:00 PM Phoenix.");
    expect(todayEmptyLead(mid)).toBeNull();
  });

  it("names the next session on a weekend", () => {
    const sat = at("2026-10-24T15:00:00Z");
    expect(sat.phase).toBe("closed");
    expect(sat.detail).toBe("Next session is Monday, 6:45 AM – 1:00 PM Phoenix.");
  });

  it("shows a turned-off EMA as off, and all off as alerts off", () => {
    expect(at("2026-10-23T16:00:00Z", { ma_240: 0 }).windows.find((w) => w.setup === "240")?.label).toBe("off");
    expect(at("2026-10-23T16:00:00Z", { ma_120: 0, ma_240: 0, ma_480: 0 }).headline).toBe("Alerts are off.");
  });
});

describe("alerts helpers", () => {
  it("shows Phoenix time all year (no daylight saving)", () => {
    expect(phoenixTime("2026-10-23T13:35:00Z")).toBe("6:35 AM");
    expect(phoenixTime("2026-11-02T14:35:00Z")).toBe("7:35 AM");
    expect(phoenixTime(null)).toBe("—");
  });

  it("risk per share and stop percent come from trigger and stop", () => {
    expect(riskPerShare(sample())).toBeCloseTo(1.12);
    expect(stopPct(sample())).toBeCloseTo((1.12 / 101.01) * 100);
  });

  it("formats R with a sign", () => {
    expect(fmtR(1.234)).toBe("+1.23R");
    expect(fmtR(-1)).toBe("-1.00R");
    expect(fmtR(null)).toBe("—");
    expect(fmtR(0.0003)).toBe("0.00R");
    expect(fmtR(-0.001)).toBe("0.00R");
  });

  it("status tone", () => {
    expect(statusTone(sample())).toBe("wait");
    expect(statusTone(sample({ status: "triggered" }))).toBe("live");
    expect(statusTone(sample({ status: "exited", r_multiple: 1.5 }))).toBe("good");
    expect(statusTone(sample({ status: "stopped", r_multiple: -1 }))).toBe("bad");
    expect(statusTone(sample({ status: "breakeven", r_multiple: 0 }))).toBe("flat");
  });

  it("chimes again when a watch triggers, never on the first load", () => {
    const watching = sample({ id: 1 });
    const fired = sample({ id: 1, status: "triggered", filled: true, fill_price: 101.01 });
    expect(triggeredAlerts([fired], null)).toEqual([]);
    expect(triggeredAlerts([fired], new Map([[1, "pending"]]))).toEqual([fired]);
    expect(triggeredAlerts([fired], new Map([[1, "triggered"]]))).toEqual([]);
    expect(triggeredAlerts([watching], new Map([[1, "pending"]]))).toEqual([]);
    expect(STATUS_LABEL.pending).toBe("Watch");
  });

  it("chimes only for alerts new since the last fetch, never on the first load or for late ones", () => {
    const a = sample({ id: 1 });
    const b = sample({ id: 2 });
    const late = sample({ id: 3, late: true });
    const read = sample({ id: 4, acknowledged: true });
    expect(freshAlerts([a, b], null)).toEqual([]);
    expect(freshAlerts([a, b, late, read], new Set([1]))).toEqual([b]);
  });

  it("plays three separate beeps", () => {
    const starts: number[] = [];
    const stops: number[] = [];
    const ctx = {
      currentTime: 10,
      destination: {},
      createGain: () => ({
        gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} },
        connect() {
          return this;
        },
      }),
      createOscillator: () => ({
        frequency: { value: 0 },
        connect() {
          return this;
        },
        start(t: number) {
          starts.push(t);
        },
        stop(t: number) {
          stops.push(t);
        },
      }),
    } as unknown as AudioContext;
    playChime(ctx);
    expect(starts).toEqual([10, 10.28, 10.56]);
    expect(stops[0]).toBeLessThanOrEqual(starts[1]);
    expect(stops[1]).toBeLessThanOrEqual(starts[2]);
  });

  it("notification text says watch, then triggered, with the levels and no emoji", () => {
    const watch = notificationText(sample(), "Pullback to rising 120 EMA");
    expect(watch.title).toBe("AAPL watch: 120 EMA (top)");
    expect(watch.body).toContain("Trigger over 101.01 (previous 15-min high + 1c), stop 99.89");
    expect(watch.body).toContain("6:35 AM Phoenix");
    const hit = notificationText(sample({ status: "triggered", filled: true, fill_price: 101.05, fill_at: "2026-10-23T13:45:00Z" }), "");
    expect(hit.title).toBe("AAPL triggered over 101.01 (top)");
    expect(hit.body).toContain("Pullback to rising 120 EMA. Filled 101.05");
    expect(hit.body).toContain("6:45 AM Phoenix");
    expect(/\p{Extended_Pictographic}/u.test(watch.title + watch.body + hit.title + hit.body)).toBe(false);
  });
});

describe("daily setup labels", () => {
  it("joins stored labels and falls back to a kind", () => {
    expect(dailySetupText(["Flat Base Breakout", { kind: "ma-overcut-fail", label: "MA Overcut and Fail (10-day)", side: "short", period: 10 }])).toBe(
      "Flat Base Breakout, MA Overcut and Fail (10-day)",
    );
    expect(dailySetupText([{ kind: "episodic-pivot" }])).toBe("episodic-pivot");
    expect(dailySetupText(undefined)).toBe("");
  });
});

describe("EMA level and settings", () => {
  it("shows the touched EMA's level", () => {
    expect(maText(sample())).toBe("99.12");
    expect(maText({ details: {} })).toBe("—");
  });
  it("has the score cut, the three EMAs and the watch length in settings", () => {
    const keys = SETTING_GROUPS.flatMap((g) => g.items.map((i) => i[0]));
    expect(keys).toEqual(
      expect.arrayContaining([
        "max_symbols", "theme_gate", "theme_top_pct", "long_pending_only", "reset_manual", "alert_manual_watchlist", "stop_mode", "fixed_stop_pct", "max_stop_pct",
        "short_hvc", "short_crossback", "short_ma10", "short_ma20", "ma_120", "ma_240", "ma_480",
        "touch_tol_pct", "hold_pct", "rising_bars", "watch_bars",
      ]),
    );
    expect(keys).not.toContain("d_hold20");
  });
  it("has one earnings-warning setting, in calendar days", () => {
    const item = SETTING_GROUPS.flatMap((g) => g.items).find((i) => i[0] === "earnings_window_days");
    expect(item?.[1]).toMatch(/within/);
    expect(item?.[2]).toMatch(/calendar days/);
  });
  it("archives after the close unless the setting is turned off", () => {
    const item = SETTING_GROUPS.flatMap((g) => g.items).find((i) => i[0] === "auto_archive");
    expect(item?.[1]).toMatch(/History/);
    expect(item?.[1]).toMatch(/4:05 PM/);
  });
});

describe("short alerts", () => {
  const a = {
    symbol: "ZZZ", setup: "s240", trigger_price: 49.5, stop_price: 51, filled: false, top: false,
    fired_at: "2026-11-06T15:00:00Z", fill_at: null, fill_price: null,
  } as unknown as TradeAlert;

  it("names and parses the short setups", () => {
    expect(isShortSetup("s240") && !isShortSetup("240")).toBe(true);
    expect(setupPeriod("s480")).toBe("480");
    expect(SETUP_NAMES.s120).toBe("Short: rally to falling 120 EMA");
  });

  it("measures risk upward from the trigger", () => {
    expect(riskPerShare(a)).toBeCloseTo(1.5);
    expect(stopPct(a)).toBeCloseTo((1.5 / 49.5) * 100);
  });

  it("words the notification for a short", () => {
    expect(notificationText(a, "").title).toBe("ZZZ short watch: 240 EMA");
    expect(notificationText(a, "").body).toMatch(/Trigger under 49.50 \(previous 15-min low - 1c\)/);
    expect(notificationText({ ...a, filled: true, fill_price: 49.4 }, "").title).toBe("ZZZ short triggered under 49.50");
  });

  it("lists the short-side settings", () => {
    const keys = SETTING_GROUPS.flatMap((g) => g.items.map((i) => i[0]));
    expect(keys).toEqual(expect.arrayContaining(["shorts", "max_short_symbols"]));
    expect(keys).not.toContain("min_score");
    expect(keys).not.toContain("short_max_rs");
  });
});


describe("alert filters", () => {
  const rows = [
    sample({ id: 1, symbol: "NVDA", setup: "120", score: 91, rs: 0.97 }),
    sample({ id: 2, symbol: "PCG", setup: "s480", score: 8, rs: 0.04 }),
    sample({ id: 3, symbol: "MU", setup: "240", score: 55, rs: 0.6 }),
    sample({ id: 4, symbol: "ZZZ", setup: "s120", score: null, rs: null }),
  ];
  const ids = (f = DEFAULT_ALERT_FILTERS, q = "") => filterAlerts(rows, f, q).map((a) => a.id);

  it("passes everything by default, including names off the scan", () => {
    expect(ids()).toEqual([1, 2, 3, 4]);
    expect(alertFiltersActive(DEFAULT_ALERT_FILTERS)).toBe(false);
  });

  it("filters by side", () => {
    expect(ids({ ...DEFAULT_ALERT_FILTERS, side: "long" })).toEqual([1, 3]);
    expect(ids({ ...DEFAULT_ALERT_FILTERS, side: "short" })).toEqual([2, 4]);
  });

  it("filters by score and RS ranges; a narrowed range drops names without a value", () => {
    expect(ids({ ...DEFAULT_ALERT_FILTERS, score: [50, 100] })).toEqual([1, 3]);
    expect(ids({ ...DEFAULT_ALERT_FILTERS, rs: [0, 10] })).toEqual([2]);
    expect(ids({ ...DEFAULT_ALERT_FILTERS, rs: [60, 60] })).toEqual([3]);
    expect(alertFiltersActive({ ...DEFAULT_ALERT_FILTERS, rs: [0, 99] })).toBe(true);
  });

  it("filters by status", () => {
    const withStatus = [
      sample({ id: 1, status: "pending" }),
      sample({ id: 2, status: "triggered", filled: true }),
      sample({ id: 3, status: "stopped", filled: true }),
    ];
    const by = (status: typeof DEFAULT_ALERT_FILTERS.status) =>
      filterAlerts(withStatus, { ...DEFAULT_ALERT_FILTERS, status }).map((a) => a.id);
    expect(by("all")).toEqual([1, 2, 3]);
    expect(by("triggered")).toEqual([2]);
    expect(by("pending")).toEqual([1]);
    expect(by("expired")).toEqual([]);
    expect(alertFiltersActive({ ...DEFAULT_ALERT_FILTERS, status: "stopped" })).toBe(true);
  });

  it("searches the ticker, any case", () => {
    expect(ids(DEFAULT_ALERT_FILTERS, "nv")).toEqual([1]);
    expect(ids(DEFAULT_ALERT_FILTERS, " M ")).toEqual([3]);
    expect(ids(DEFAULT_ALERT_FILTERS, "QQQ")).toEqual([]);
  });

  it("resets saved filters that are missing or malformed", () => {
    expect(normalizeAlertFilters(null)).toEqual(DEFAULT_ALERT_FILTERS);
    expect(normalizeAlertFilters({ score: [80, 20], rs: [10, 90], side: "sideways", status: "lost" })).toEqual({
      score: [0, 100],
      rs: [10, 90],
      side: "all",
      status: "all",
    });
    expect(normalizeAlertFilters({ status: "triggered" }).status).toBe("triggered");
  });

  it("colours RS on the score cuts", () => {
    expect([rsLevel(0.93), rsLevel(0.7), rsLevel(0.55), rsLevel(0.49)]).toEqual(["hi", "hi", "mid", "lo"]);
  });
});

describe("alert table sort", () => {
  const rows = [
    sample({ id: 1, symbol: "MU", r_multiple: null, open_r: 0.5, score: 40, fired_at: "2026-10-23T15:00:00Z" }),
    sample({ id: 2, symbol: "AAPL", r_multiple: 2, open_r: null, score: 90, fired_at: "2026-10-23T14:00:00Z" }),
    sample({ id: 3, symbol: "ZZZ", r_multiple: -1, open_r: null, score: null, fired_at: "2026-10-23T16:00:00Z" }),
  ];

  it("keeps the current order until a header is clicked", () => {
    expect(sortByColumn(rows, null, alertSortValue).map((r) => r.id)).toEqual([1, 2, 3]);
  });

  it("sorts R numerically with blanks at the bottom, then reverses", () => {
    const high = toggleColumnSort(null, "r");
    expect(high).toEqual({ key: "r", dir: -1 });
    expect(sortByColumn(rows, high, alertSortValue).map((r) => r.symbol)).toEqual(["AAPL", "ZZZ", "MU"]);
    const low = toggleColumnSort(high, "r");
    expect(low.dir).toBe(1);
    expect(sortByColumn(rows, low, alertSortValue).map((r) => r.symbol)).toEqual(["ZZZ", "AAPL", "MU"]);
  });

  it("sorts tickers A to Z, and time newest first", () => {
    expect(sortByColumn(rows, toggleColumnSort(null, "symbol"), alertSortValue).map((r) => r.symbol)).toEqual(["AAPL", "MU", "ZZZ"]);
    expect(sortByColumn(rows, toggleColumnSort(null, "fired_at"), alertSortValue).map((r) => r.id)).toEqual([3, 1, 2]);
  });

  it("puts a missing score at the bottom either way", () => {
    const desc = toggleColumnSort(null, "score");
    const asc = toggleColumnSort(desc, "score");
    expect(sortByColumn(rows, desc, alertSortValue).at(-1)?.symbol).toBe("ZZZ");
    expect(sortByColumn(rows, asc, alertSortValue).at(-1)?.symbol).toBe("ZZZ");
  });
});
