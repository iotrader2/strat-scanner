import type { AlertStatus, DailySetupRef, TradeAlert } from "./api";

/** Market times are shown in the user's zone (Arizona, no daylight saving). */
export const ALERT_TZ = "America/Phoenix";

const timeFmt = new Intl.DateTimeFormat("en-US", { timeZone: ALERT_TZ, hour: "numeric", minute: "2-digit" });

/** "6:35 AM" style, Phoenix time. */
export function phoenixTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : timeFmt.format(d);
}

const stampFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: ALERT_TZ,
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  hour12: true,
  timeZoneName: "short",
});

/** "Tue Nov 10, 2:01 PM MST". Phoenix has no daylight time, so the zone is always MST. A dash if missing. */
export function phoenixStamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const parts = stampFmt.formatToParts(d);
  const pick = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? "";
  return `${pick("weekday")} ${pick("month")} ${pick("day")}, ${pick("hour")}:${pick("minute")} ${pick("dayPeriod")} ${pick("timeZoneName")}`;
}

/** Alert bars are 15-minute candles. Keep in step with `BAR_MINUTES` in backend/strat/alerts.py. */
export const BAR_MINUTES = 15;

/** The EMAs on the 15-minute chart that alerts watch. Keep in step with `MA_PERIODS` in backend/strat/alerts.py. */
export const ALERT_EMAS = ["120", "240", "480"] as const;

export const SETUP_NAMES: Record<string, string> = {
  "6": "15-min 6 EMA crossback",
  "120": "Pullback to rising 120 EMA",
  "240": "Pullback to rising 240 EMA",
  "480": "Pullback to rising 480 EMA",
  s120: "Short: rally to falling 120 EMA",
  s240: "Short: rally to falling 240 EMA",
  s480: "Short: rally to falling 480 EMA",
};

/** Labels for the Daily setup column. A stored object uses its friendly label; an older row stored the label itself. */
export function dailySetupText(setups: ReadonlyArray<string | Partial<DailySetupRef>> | null | undefined): string {
  if (!setups?.length) return "";
  return setups
    .map((setup) => (typeof setup === "string" ? setup : setup.label || setup.kind || ""))
    .filter(Boolean)
    .join(", ");
}

/** Legacy short setup key ("s120" / "s240" / "s480"). */
export const isShortSetup = (setup: string): boolean => setup.startsWith("s");
/** Inverse-ETF short proxy: a long on the mapped ETF tagged with an underlying. */
export const isInverseShortAlert = (a: { details?: { inverse_etf?: boolean; side_role?: string } | null }): boolean =>
  Boolean(a.details?.inverse_etf || a.details?.side_role === "short");
/** Short chip: legacy s* setup or inverse-ETF tagged alert. */
export const isShortAlert = (a: { setup: string; details?: { inverse_etf?: boolean; side_role?: string } | null }): boolean =>
  isShortSetup(a.setup) || isInverseShortAlert(a);
/** The EMA period of a long or short setup key. */
export const setupPeriod = (setup: string): string => setup.replace(/^s/, "");

/** One-line rule, shown on hover over the setup column. */
export const SETUP_RULES: Record<string, string> = Object.fromEntries([
  [
    "6",
    "A completed 15-minute bar closes above the 6 EMA after the prior close was at or below it. Buy the high + 1c; stop at the low - 1c. No re-arm. Trim in thirds on closes back through the 6 / 20 / 120 EMAs.",
  ],
  ...ALERT_EMAS.map((p) => [
    p,
    `A name with a long daily setup pulls back from above to the rising ${p} EMA on the 15-minute chart and holds it. Watch; the trigger is the previous 15-minute candle's high + 1c. The stop follows the stop rule (lowest low, this candle, or a fixed percent).`,
  ]),
  ...ALERT_EMAS.map((p) => [
    `s${p}`,
    `Short: a name with a short daily setup rallies from below up into the falling ${p} EMA (resistance) on the 15-minute chart and is held under it. Watch; the trigger is the previous 15-minute candle's low - 1c. The stop follows the stop rule.`,
  ]),
]);

const ET = "America/New_York";

export type AlertDayPhase = "before" | "open" | "done" | "closed";
export type SetupWindowState = "later" | "open" | "done";

export interface SetupWindowView {
  /** The EMA period ("120" / "240" / "480"). */
  setup: string;
  /** Clock range in Phoenix, or "off" when that EMA is turned off in the settings. */
  label: string;
  state: SetupWindowState;
}

export interface AlertDayStatus {
  phase: AlertDayPhase;
  headline: string;
  detail: string;
  windows: SetupWindowView[];
}

interface Clock {
  hm: string;
  period: string;
  full: string;
}

function zonedParts(date: Date, timeZone: string): { year: number; month: number; day: number; hour: number; minute: number; weekday: string } {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    weekday: "short",
  });
  const bag: Record<string, string> = {};
  for (const p of fmt.formatToParts(date)) if (p.type !== "literal") bag[p.type] = p.value;
  let hour = Number(bag.hour);
  if (hour === 24) hour = 0;
  return { year: Number(bag.year), month: Number(bag.month), day: Number(bag.day), hour, minute: Number(bag.minute), weekday: bag.weekday };
}

/** A wall-clock time in `timeZone` as an absolute instant. 9:30 New York is never a DST gap. */
function zonedDateTime(timeZone: string, year: number, month: number, day: number, hour: number, minute: number): Date {
  const utcGuess = Date.UTC(year, month - 1, day, hour, minute);
  const parts = zonedParts(new Date(utcGuess), timeZone);
  const asUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute);
  return new Date(utcGuess - (asUtc - utcGuess));
}

function shiftDate(year: number, month: number, day: number, days: number): { year: number; month: number; day: number } {
  const t = new Date(Date.UTC(year, month - 1, day + days));
  return { year: t.getUTCFullYear(), month: t.getUTCMonth() + 1, day: t.getUTCDate() };
}

/** Minutes from the 9:30 ET open to the noon ET trade cutoff. */
export const TRADE_WINDOW_MINUTES = 150;

function phoenixClock(date: Date): Clock {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: ALERT_TZ, hour: "numeric", minute: "2-digit" }).formatToParts(date);
  const hour = parts.find((p) => p.type === "hour")?.value ?? "";
  const minute = parts.find((p) => p.type === "minute")?.value ?? "";
  const period = parts.find((p) => p.type === "dayPeriod")?.value ?? "";
  return { hm: `${hour}:${minute}`, period, full: `${hour}:${minute} ${period}` };
}

function rangeLabel(start: Date, end: Date): string {
  const a = phoenixClock(start);
  const b = phoenixClock(end);
  if (a.full === b.full) return a.full;
  if (a.period === b.period) return `${a.hm}–${b.hm} ${a.period}`;
  return `${a.full} – ${b.full}`;
}

/**
 * Whether alerts are running, and which EMAs are watched, in Phoenix time.
 * Alerts run from the close of the opening 15-minute candle (9:45 New York) to the 12:00 noon New York cutoff
 * (the backend trade window: no new alert or entry after it).
 * `now` defaults to the current instant. Weekends use the next session's clock times.
 */
export function alertDayStatus(now: Date = new Date(), settings?: Record<string, number>): AlertDayStatus {
  const here = zonedParts(now, ET);
  const weekend = here.weekday === "Sat" || here.weekday === "Sun";
  const session = weekend ? shiftDate(here.year, here.month, here.day, here.weekday === "Sat" ? 2 : 1) : { year: here.year, month: here.month, day: here.day };
  const open = zonedDateTime(ET, session.year, session.month, session.day, 9, 30);
  const first = new Date(open.getTime() + BAR_MINUTES * 60_000);
  const last = new Date(open.getTime() + TRADE_WINDOW_MINUTES * 60_000);
  const span = rangeLabel(first, last);
  const state: SetupWindowState = weekend || now < first ? "later" : now <= last ? "open" : "done";
  const on = (p: string) => (settings?.[`ma_${p}`] ?? 1) !== 0;
  const windows: SetupWindowView[] = ALERT_EMAS.map((p) => ({ setup: p, label: on(p) ? span : "off", state: on(p) ? state : "done" }));
  const weekday = new Intl.DateTimeFormat("en-US", { timeZone: ET, weekday: "long" }).format(open);

  if (!ALERT_EMAS.some(on)) return { phase: "done", headline: "Alerts are off.", detail: "No moving average is turned on.", windows };
  if (weekend) return { phase: "closed", headline: "Market is closed.", detail: `Next session is ${weekday}, ${span} Phoenix.`, windows };
  if (now < first) return { phase: "before", headline: `Alerts start at ${phoenixClock(first).full} Phoenix.`, detail: `Session ${span} Phoenix.`, windows };
  if (now > last) return { phase: "done", headline: "Alerts are done for the day.", detail: `The session was ${span} Phoenix.`, windows };
  return { phase: "open", headline: `Watching for pullbacks until ${phoenixClock(last).full} Phoenix.`, detail: `Session ${span} Phoenix.`, windows };
}

/** Lead sentence for an empty Today list. Null keeps the "no alerts yet" copy. */
export function todayEmptyLead(day: AlertDayStatus): string | null {
  if (day.phase === "done" || day.phase === "closed") return `${day.headline} ${day.detail}`;
  return null;
}

export const STATUS_LABEL: Record<AlertStatus, string> = {
  pending: "Watch",
  triggered: "Triggered",
  stopped: "Stopped",
  breakeven: "Break-even",
  exited: "Exited",
  expired: "Expired",
  cancelled: "Cancelled",
};

export function statusTone(a: Pick<TradeAlert, "status" | "r_multiple">): "live" | "good" | "bad" | "flat" | "wait" {
  if (a.status === "pending") return "wait";
  if (a.status === "triggered") return "live";
  if (a.status === "expired" || a.status === "cancelled" || a.status === "breakeven") return "flat";
  if (a.r_multiple == null) return "flat";
  const r = Math.round(a.r_multiple * 100) / 100;
  return r > 0 ? "good" : r < 0 ? "bad" : "flat";
}

/** Planned risk per share: distance from the trigger to the stop (a short's stop is above). */
export function riskPerShare(a: Pick<TradeAlert, "trigger_price" | "stop_price">): number {
  return Math.abs(a.trigger_price - a.stop_price);
}

/** Stop distance as a percent of the entry (trigger) price. */
export function stopPct(a: Pick<TradeAlert, "trigger_price" | "stop_price">): number {
  return a.trigger_price > 0 ? (Math.abs(a.trigger_price - a.stop_price) / a.trigger_price) * 100 : 0;
}

/** R to two decimals; a scratch that rounds to 0.00 shows without a sign. */
export function fmtR(r: number | null | undefined): string {
  if (r == null) return "—";
  const v = Math.round(r * 100) / 100;
  return `${v > 0 ? "+" : ""}${(v === 0 ? 0 : v).toFixed(2)}R`;
}

export function rTone(r: number | null | undefined): string {
  if (r == null) return "";
  const v = Math.round(r * 100) / 100;
  return v > 0 ? "green-text" : v < 0 ? "red-text" : "";
}

function px(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

/** The "What happened" sentence. Also the text that column sorts by. */
export function happenedText(a: TradeAlert): string {
  const short = isShortSetup(a.setup);
  const ema = `${setupPeriod(a.setup)} EMA`;
  if (a.status === "pending") {
    return short
      ? `Watching: trigger under ${px(a.setup_low)} (last 15-min low)`
      : `Watching: trigger over ${px(a.setup_high)} (last 15-min high)`;
  }
  if (a.status === "expired") {
    if (a.exit_reason === "max_attempts") return "Expired: 2 attempts already";
    if (a.exit_reason === "session_end") return "Not triggered by the close";
    if (a.exit_reason === "trade_window") return "Not triggered by the 12:00 ET cutoff";
    return "Not triggered in time";
  }
  if (a.status === "cancelled") return `Closed ${short ? "over" : "under"} the ${ema} before triggering`;
  const parts = [`Filled ${px(a.fill_price)} at ${phoenixTime(a.fill_at)}`];
  if (a.breakeven_at) parts.push(`stop to break-even ${phoenixTime(a.breakeven_at)}`);
  if (a.exit_price != null) {
    const why =
      a.exit_reason === "close_under_ma"
        ? `close under ${ema}`
        : a.exit_reason === "close_over_ma"
          ? `close over ${ema}`
          : a.exit_reason === "session_end"
            ? "session end"
            : "stop";
    parts.push(`out ${px(a.exit_price)} at ${phoenixTime(a.exit_at)} (${why})`);
  }
  return parts.join(", ");
}

export const ALERT_SORT_KEYS = [
  "fired_at", "symbol", "score", "rs", "side", "daily_setup", "industry", "entry",
  "ema", "trigger", "stop", "stop_pct", "risk", "status", "best", "open_r", "r", "outcome",
] as const;
export type AlertSortKey = (typeof ALERT_SORT_KEYS)[number];

export const METRIC_SORT_KEYS = [
  "name", "count", "filled", "fill_rate", "closed", "win_rate", "avg_r", "total_r", "open",
] as const;
export type MetricSortKey = (typeof METRIC_SORT_KEYS)[number];

export type ColumnSort = { key: string; dir: 1 | -1 };

/** No sort until a header is clicked. A saved value for a column that no longer exists is ignored. */
export function normalizeColumnSort(saved: unknown, keys: readonly string[]): ColumnSort | null {
  if (!saved || typeof saved !== "object") return null;
  const key = (saved as { key?: unknown }).key;
  const dir = (saved as { dir?: unknown }).dir;
  if (typeof key !== "string" || !keys.includes(key)) return null;
  if (dir !== 1 && dir !== -1) return null;
  return { key, dir };
}

const TEXT_SORT = new Set<string>(["symbol", "side", "daily_setup", "industry", "entry", "status", "outcome", "name"]);

/** First click: A→Z for text, newest or largest first for time and numbers. The next click flips. */
export function toggleColumnSort(current: ColumnSort | null, key: string): ColumnSort {
  if (current?.key === key) return { key, dir: current.dir === 1 ? -1 : 1 };
  return { key, dir: TEXT_SORT.has(key) ? 1 : -1 };
}

function blank(v: number | string | null): v is null {
  return v == null || v === "" || (typeof v === "number" && !Number.isFinite(v));
}

/** Blank and dash cells stay at the bottom in either direction. The original order is kept until `sort` is set. */
export function sortByColumn<T>(rows: readonly T[], sort: ColumnSort | null, value: (row: T, key: string) => number | string | null): T[] {
  if (!sort) return [...rows];
  const dir = sort.dir;
  return [...rows].sort((a, b) => {
    const av = value(a, sort.key);
    const bv = value(b, sort.key);
    if (blank(av) && blank(bv)) return 0;
    if (blank(av)) return 1;
    if (blank(bv)) return -1;
    if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir;
    return (Number(av) - Number(bv)) * dir;
  });
}

export function alertSortValue(a: TradeAlert, key: string): number | string | null {
  switch (key) {
    case "fired_at": {
      const t = a.fired_at ? Date.parse(a.fired_at) : NaN;
      return Number.isFinite(t) ? t : null;
    }
    case "symbol":
      return a.symbol || null;
    case "score":
      return a.score ?? null;
    case "rs":
      return a.rs ?? null;
    case "side":
      return isShortSetup(a.setup) ? "Short" : "Long";
    case "daily_setup":
      return dailySetupText(a.details?.daily_setups) || null;
    case "industry":
      return a.industry || null;
    case "entry":
      return SETUP_NAMES[a.setup] ?? a.setup ?? null;
    case "ema":
      return a.details?.ma ?? null;
    case "trigger":
      return a.trigger_price ?? null;
    case "stop":
      return a.stop_price ?? null;
    case "stop_pct":
      return a.trigger_price > 0 ? stopPct(a) : null;
    case "risk":
      return Number.isFinite(a.trigger_price) && Number.isFinite(a.stop_price) ? riskPerShare(a) : null;
    case "status":
      return STATUS_LABEL[a.status] ?? a.status ?? null;
    case "best":
      return a.high_reached ?? null;
    case "open_r":
      return a.open_r ?? null;
    case "r":
      return a.r_multiple ?? null;
    case "outcome":
      return happenedText(a) || null;
    default:
      return null;
  }
}

/**
 * Alerts that should chime: not seen in an earlier fetch of this page load, not found late, not yet acknowledged.
 * `seen` null means this is the first fetch, which never chimes (the alerts were already there).
 */
export function freshAlerts(alerts: TradeAlert[], seen: Set<number> | null): TradeAlert[] {
  if (seen === null) return [];
  return alerts.filter((a) => !seen.has(a.id) && !a.late && !a.acknowledged);
}

/**
 * Watch alerts that have just triggered: seen as "pending" in an earlier fetch of this page load and filled now.
 * `before` is the status each alert had in the previous fetch (null on the first fetch, which never chimes).
 */
export function triggeredAlerts(alerts: TradeAlert[], before: Map<number, string> | null): TradeAlert[] {
  if (before === null) return [];
  return alerts.filter((a) => before.get(a.id) === "pending" && a.filled);
}

export function notificationText(a: TradeAlert, setupName: string): { title: string; body: string } {
  const name = setupName || SETUP_NAMES[a.setup] || `EMA ${a.setup}`;
  const short = isShortSetup(a.setup);
  if (a.filled) {
    return {
      title: `${a.symbol} ${short ? "short triggered under" : "triggered over"} ${a.trigger_price.toFixed(2)}${a.top ? " (top)" : ""}`,
      body: `${name}. Filled ${(a.fill_price ?? a.trigger_price).toFixed(2)}, stop ${a.stop_price.toFixed(2)} (${stopPct(a).toFixed(2)}%). ${phoenixTime(a.fill_at)} Phoenix.`,
    };
  }
  return {
    title: `${a.symbol} ${short ? "short watch" : "watch"}: ${setupPeriod(a.setup)} EMA${a.top ? " (top)" : ""}`,
    body: `${name}. ${short ? `Trigger under ${a.trigger_price.toFixed(2)} (previous 15-min low - 1c)` : `Trigger over ${a.trigger_price.toFixed(2)} (previous 15-min high + 1c)`}, stop ${a.stop_price.toFixed(2)} (${stopPct(a).toFixed(2)}%). ${phoenixTime(a.fired_at)} Phoenix.`,
  };
}

/** Three short beeps made with Web Audio, so no sound file has to load. */
export function playChime(ctx: AudioContext): void {
  const now = ctx.currentTime;
  const beep = 0.14;
  const step = 0.28;
  for (let i = 0; i < 3; i++) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = 880;
    const t = now + i * step;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.25, t + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + beep);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + beep + 0.02);
  }
}

/** The EMA level the stock pulled back to, and its color on the 15-minute chart. */
export function maText(a: Pick<TradeAlert, "details">): string {
  const v = a.details?.ma;
  return v == null || !Number.isFinite(v) ? "—" : v.toFixed(2);
}

/** Hover text: every EMA on the touch candle and how much the one touched was rising. */
export function maTitle(a: Pick<TradeAlert, "setup" | "details">): string {
  const d = a.details ?? {};
  const values = Object.entries(d.ma_values ?? {})
    .filter(([, v]) => v != null)
    .map(([p, v]) => `${p} EMA ${(v as number).toFixed(2)}`);
  const slope = d.ma_slope_pct == null ? "" : `, rising ${d.ma_slope_pct.toFixed(2)}% over the check`;
  return values.length ? `On the touch candle: ${values.join(", ")}${slope}` : `15-minute ${a.setup} EMA`;
}

/** Human labels and grouping for the settings form. */
export const SETTING_GROUPS: { title: string; items: [key: string, label: string, unit?: string][] }[] = [
  {
    title: "Which names",
    items: [
      ["max_symbols", "Long daily setups: check at most (highest score first)", "names"],
      ["theme_gate", "Theme gate (1 = on, 0 = off): longs in a top theme, shorts in a bottom theme", ""],
      ["theme_top_pct", "Theme band", "% of themes (25 = the top or bottom quartile)"],
      ["long_pending_only", "Longs: only a daily setup that has not broken yet (1 = on, 0 = off)", ""],
      ["reset_manual", "Watchlist reset one minute after the 4:00 PM New York close also clears names you added (1 = on, 0 = off). Alert names are always cleared. That is 2:01 PM Phoenix in winter and 1:01 PM Phoenix in summer.", ""],
      ["alert_manual_watchlist", "Also alert names you added yourself, long side, even with no daily setup (1 = on, 0 = off). They do not count toward the name cap.", ""],
    ],
  },
  {
    title: "Short side (inverse ETFs)",
    items: [
      ["shorts", "Alert short daily setups via mapped inverse ETFs (1 = on, 0 = off)", ""],
      ["inverse_etf_shorts", "Use inverse ETF longs for shorts (1 = on, 0 = off)", ""],
      ["max_short_symbols", "Check at most (weakest RS first)", "names"],
      ["shorts_ma120_enabled", "Legacy: short entries on the 120 EMA / s120 (1 = on, 0 = off). Unused when inverse ETFs are on", ""],
      ["short_crossback", "EMA Crossback Short (1 = on, 0 = off). Default on; drives inverse ETF alerts", ""],
      ["short_ma10", "MA Overcut and Fail, 10-day (1 = on, 0 = off)", ""],
      ["short_ma20", "MA Overcut and Fail, 20-day (1 = on, 0 = off)", ""],
      ["short_ma50", "MA Overcut and Fail, 50-day (1 = on, 0 = off)", ""],
      ["short_hvc", "Delayed HVC Short (1 = on, 0 = off)", ""],
      ["short_overcut", "Overcut and Fail (1 = on, 0 = off)", ""],
      ["short_wedge", "Wedge Drop (1 = on, 0 = off)", ""],
      ["short_flat", "Flat Base Breakdown (1 = on, 0 = off)", ""],
      ["short_flag", "Low Tight Flag (1 = on, 0 = off)", ""],
      ["short_gap", "Gap-Down Episodic Pivot (1 = on, 0 = off)", ""],
    ],
  },
  {
    title: "Entry trigger (15-minute chart)",
    items: [
      ["entry_trigger", "Entry: 1 = 6 EMA crossback (default), 0 = pullback to rising 120/240/480", ""],
      ["cross_ema_period", "Crossback EMA period", ""],
      ["trim_ema_1", "Trim 1/3 on close through this EMA (against the position)", ""],
      ["trim_ema_2", "Trim next 1/3 on close through this EMA", ""],
      ["trim_ema_3", "Trim last 1/3 on close through this EMA", ""],
      ["breakeven_after_bars", "Crossback: stop to break-even after", "completed bars after the fill"],
      ["ma_120", "MA-touch mode: 120 EMA, red (1 = on, 0 = off)", ""],
      ["ma_240", "MA-touch mode: 240 EMA, yellow (1 = on, 0 = off)", ""],
      ["ma_480", "MA-touch mode: 480 EMA, blue (1 = on, 0 = off)", ""],
      ["long_ext_ema_period", "Long extension cap: prior-day daily EMA period", ""],
      ["long_max_ext_vs_d10ema_pct", "Skip a long when the buy is more than this % above that prior-day EMA (0 = off)", "%"],
      ["long_ext_waive_at_d4ema", "Keep a long over the cap when the buy is at or under the prior-day daily 4 EMA (1 = on, 0 = off)", ""],
      ["touch_tol_pct", "MA-touch: low within", "% over the EMA"],
      ["hold_pct", "Lost the EMA: a close more than", "% under it"],
      ["rising_bars", "MA-touch rising: higher than", "candles earlier"],
    ],
  },
  {
    title: "Stop",
    items: [
      ["stop_mode", "MA-touch stop: 0 = lowest low since the touch, 1 = this candle only, 2 = fixed percent (crossback always uses the candle)", ""],
      ["fixed_stop_pct", "Fixed stop", "% of the buy (shorts: of the sell)"],
      ["max_stop_pct", "Skip an order whose stop is wider than (default 1)", "%"],
    ],
  },
  {
    title: "Trigger and tracking",
    items: [
      ["watch_bars", "MA-touch: watch for a trigger for", "15-min candles after the touch"],
      ["max_attempts", "Triggered attempts per name per day", ""],
      ["breakeven_after_new_highs", "MA-touch: stop to break-even after", "new-high candles"],
      ["exit_close_under_ma", "MA-touch: exit on a close under the EMA (1 = on, 0 = off)", ""],
      ["top_names", "Top names per day", ""],
    ],
  },
  {
    title: "Earnings warning",
    items: [
      ["earnings_window_days", "Show the warning when earnings are within", "calendar days, including today"],
    ],
  },
  {
    title: "After the close",
    items: [
      ["auto_archive", "Move the day's alerts to History after 4:05 PM New York (1 = on, 0 = off)", ""],
    ],
  },
];

/** Alerts table filters: score and RS ranges (0-100, RS as a percentile) and the side. Full ranges filter nothing. */
export interface AlertFilters {
  score: [number, number];
  rs: [number, number];
  side: "all" | "long" | "short";
  status: "all" | AlertStatus;
}

export const DEFAULT_ALERT_FILTERS: AlertFilters = { score: [0, 100], rs: [0, 100], side: "all", status: "all" };

/** Saved filters, with anything missing or malformed reset to the default. */
export function normalizeAlertFilters(raw: unknown): AlertFilters {
  const f = (raw ?? {}) as Partial<AlertFilters>;
  const range = (v: unknown): [number, number] => {
    if (!Array.isArray(v) || v.length !== 2) return [0, 100];
    const lo = Math.max(0, Math.min(100, Number(v[0])));
    const hi = Math.max(0, Math.min(100, Number(v[1])));
    return Number.isFinite(lo) && Number.isFinite(hi) && lo <= hi ? [lo, hi] : [0, 100];
  };
  return {
    score: range(f.score),
    rs: range(f.rs),
    side: f.side === "long" || f.side === "short" ? f.side : "all",
    status: typeof f.status === "string" && f.status in STATUS_LABEL ? (f.status as AlertStatus) : "all",
  };
}

export function alertFiltersActive(f: AlertFilters): boolean {
  return f.side !== "all" || f.status !== "all" || f.score[0] > 0 || f.score[1] < 100 || f.rs[0] > 0 || f.rs[1] < 100;
}

function inRange(v: number | null | undefined, [lo, hi]: [number, number]): boolean {
  if (lo <= 0 && hi >= 100) return true;
  return v != null && v >= lo && v <= hi;
}

/**
 * Alerts that pass the filters and whose ticker contains ``ticker`` (any case). A narrowed score or RS range drops names with no score / RS (off the scan).
 * RS is compared as a whole percentile (0.934 → 93), the same number the RS column shows.
 */
export function filterAlerts<T extends Pick<TradeAlert, "symbol" | "setup" | "score" | "rs" | "status">>(
  alerts: T[],
  f: AlertFilters,
  ticker = "",
): T[] {
  const q = ticker.trim().toUpperCase();
  return alerts.filter((a) => {
    if (q && !a.symbol.toUpperCase().includes(q)) return false;
    if (f.side === "long" && isShortSetup(a.setup)) return false;
    if (f.side === "short" && !isShortSetup(a.setup)) return false;
    if (f.status !== "all" && a.status !== f.status) return false;
    if (!inRange(a.score, f.score)) return false;
    return inRange(a.rs == null ? null : Math.round(a.rs * 100), f.rs);
  });
}

/** Pill tone for an RS percentile, on the same cuts as the score pill: ≥ P70 green, ≥ P50 blue, else red. */
export function rsLevel(rs: number): "hi" | "mid" | "lo" {
  const p = Math.round(rs * 100);
  return p >= 70 ? "hi" : p >= 50 ? "mid" : "lo";
}
