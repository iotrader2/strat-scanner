import type { AlertStatus, TradeAlert } from "./api";

/** Market times are shown in the user's zone (Arizona, no daylight saving). */
export const ALERT_TZ = "America/Phoenix";

const timeFmt = new Intl.DateTimeFormat("en-US", { timeZone: ALERT_TZ, hour: "numeric", minute: "2-digit" });

/** "6:35 AM" style, Phoenix time. */
export function phoenixTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : timeFmt.format(d);
}

/** Alert bars are 15-minute candles. Keep in step with `BAR_MINUTES` in backend/strat/alerts.py. */
export const BAR_MINUTES = 15;

/** The EMAs on the 15-minute chart that alerts watch. Keep in step with `MA_PERIODS` in backend/strat/alerts.py. */
export const ALERT_EMAS = ["120", "240", "480"] as const;

export const SETUP_NAMES: Record<string, string> = {
  "120": "Pullback to rising 120 EMA",
  "240": "Pullback to rising 240 EMA",
  "480": "Pullback to rising 480 EMA",
  s120: "Short: rally to falling 120 EMA",
  s240: "Short: rally to falling 240 EMA",
  s480: "Short: rally to falling 480 EMA",
};

/** Short-side alert ("s120" / "s240" / "s480"): sell stop under the candle low, stop above the rally high. */
export const isShortSetup = (setup: string): boolean => setup.startsWith("s");
/** The EMA period of a long or short setup key. */
export const setupPeriod = (setup: string): string => setup.replace(/^s/, "");

/** One-line rule, shown on hover over the setup column. */
export const SETUP_RULES: Record<string, string> = Object.fromEntries([
  ...ALERT_EMAS.map((p) => [
    p,
    `A high-score stock pulls back from above to the rising ${p} EMA on the 15-minute chart and holds it. Watch; the trigger is the previous 15-minute candle's high + 1c.`,
  ]),
  ...ALERT_EMAS.map((p) => [
    `s${p}`,
    `Short: a laggard rallies from below up to the falling ${p} EMA on the 15-minute chart and is held under it. Watch; the trigger is the previous 15-minute candle's low - 1c, the stop the rally high + 1c.`,
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
 * Alerts run from the close of the opening 15-minute candle (9:45 New York) to the 4:00 close.
 * `now` defaults to the current instant. Weekends use the next session's clock times.
 */
export function alertDayStatus(now: Date = new Date(), settings?: Record<string, number>): AlertDayStatus {
  const here = zonedParts(now, ET);
  const weekend = here.weekday === "Sat" || here.weekday === "Sun";
  const session = weekend ? shiftDate(here.year, here.month, here.day, here.weekday === "Sat" ? 2 : 1) : { year: here.year, month: here.month, day: here.day };
  const open = zonedDateTime(ET, session.year, session.month, session.day, 9, 30);
  const first = new Date(open.getTime() + BAR_MINUTES * 60_000);
  const last = new Date(open.getTime() + 390 * 60_000);
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
    title: "Which stocks",
    items: [
      ["min_score", "Universe stocks with a scan score of at least", ""],
      ["max_symbols", "Check at most (highest score first)", "names"],
    ],
  },
  {
    title: "Short side (laggards)",
    items: [
      ["shorts", "Alert short setups too: rallies into a falling EMA (1 = on, 0 = off)", ""],
      ["short_max_rs", "Laggards: RS at or below percentile", "(trend broken)"],
      ["max_short_symbols", "Check at most (weakest RS first)", "names"],
    ],
  },
  {
    title: "Pullback to a rising EMA (15-minute chart)",
    items: [
      ["ma_120", "120 EMA, red (1 = on, 0 = off)", ""],
      ["ma_240", "240 EMA, yellow (1 = on, 0 = off)", ""],
      ["ma_480", "480 EMA, blue (1 = on, 0 = off)", ""],
      ["touch_tol_pct", "Touch: low within", "% over the EMA"],
      ["hold_pct", "Lost the EMA: a close more than", "% under it"],
      ["rising_bars", "Rising: higher than", "candles earlier"],
    ],
  },
  {
    title: "Trigger and tracking",
    items: [
      ["watch_bars", "Watch for a trigger for", "15-min candles after the touch"],
      ["max_attempts", "Triggered attempts per name per day", ""],
      ["breakeven_after_new_highs", "Stop to break-even after", "new-high candles"],
      ["exit_close_under_ma", "Exit on a close under the EMA (1 = on, 0 = off)", ""],
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
