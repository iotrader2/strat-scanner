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

/**
 * Setup windows are minutes after the 9:30 America/New_York open, on the setup bar's start
 * (`lo <= barIndex * 5 <= hi`). The alert is created when that bar closes, five minutes later.
 * A is only the opening bar. These defaults match `Settings` in backend/strat/alerts.py.
 */
const WINDOW_DEFAULTS: Record<string, number> = {
  b_from: 5,
  b_to: 25,
  c_from: 5,
  c_to: 25,
  d_from: 25,
  d_to: 60,
  e_from: 10,
  e_to: 80,
  f_from: 120,
  f_to: 385,
};

const SETUPS = ["A", "B", "C", "D", "E", "F"] as const;
const ET = "America/New_York";

export type AlertDayPhase = "before" | "open" | "done" | "closed";
export type SetupWindowState = "later" | "open" | "done";

export interface SetupWindowView {
  setup: string;
  /** Clock range in Phoenix, or "off" when the saved minutes contain no 5-minute bar. */
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

function windowMinutes(settings: Record<string, number> | undefined, key: string): number {
  const v = settings?.[key];
  return typeof v === "number" && Number.isFinite(v) ? v : WINDOW_DEFAULTS[key];
}

/** Minutes after the open when the alert can print (bar close), or null when no bar falls in the window. */
function fireMinutes(setup: string, settings: Record<string, number> | undefined): { first: number; last: number } | null {
  const from = setup === "A" ? 0 : windowMinutes(settings, `${setup.toLowerCase()}_from`);
  const to = setup === "A" ? 0 : windowMinutes(settings, `${setup.toLowerCase()}_to`);
  if (to < from) return null;
  const firstStart = Math.ceil(from / 5) * 5;
  const lastStart = Math.floor(to / 5) * 5;
  if (firstStart > lastStart) return null;
  return { first: firstStart + 5, last: lastStart + 5 };
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

function joinSetups(setups: string[]): string {
  if (setups.length <= 1) return setups[0] ?? "";
  if (setups.length === 2) return `${setups[0]} and ${setups[1]}`;
  return `${setups.slice(0, -1).join(", ")} and ${setups[setups.length - 1]}`;
}

interface BuiltWindow extends SetupWindowView {
  first: number;
  last: number;
}

/**
 * Whether new alerts can still fire, and each setup's window in Phoenix time.
 * `now` defaults to the current instant. Weekends use the next session's clock times.
 */
export function alertDayStatus(now: Date = new Date(), settings?: Record<string, number>): AlertDayStatus {
  const here = zonedParts(now, ET);
  const weekend = here.weekday === "Sat" || here.weekday === "Sun";
  const session = weekend ? shiftDate(here.year, here.month, here.day, here.weekday === "Sat" ? 2 : 1) : { year: here.year, month: here.month, day: here.day };
  const open = zonedDateTime(ET, session.year, session.month, session.day, 9, 30);
  const at = (minutes: number) => new Date(open.getTime() + minutes * 60_000);

  const built: BuiltWindow[] = SETUPS.map((setup) => {
    const span = fireMinutes(setup, settings);
    if (!span) return { setup, label: "off", state: "done" as const, first: Number.POSITIVE_INFINITY, last: Number.NEGATIVE_INFINITY };
    const firstAt = at(span.first);
    const lastAt = at(span.last);
    const state: SetupWindowState = now < firstAt ? "later" : now <= lastAt ? "open" : "done";
    return { setup, label: rangeLabel(firstAt, lastAt), state, first: firstAt.getTime(), last: lastAt.getTime() };
  });

  const active = built.filter((w) => w.label !== "off");
  const first = active.reduce((min, w) => Math.min(min, w.first), Number.POSITIVE_INFINITY);
  const last = active.reduce((max, w) => Math.max(max, w.last), Number.NEGATIVE_INFINITY);
  const span = active.length ? rangeLabel(new Date(first), new Date(last)) : "";
  const weekday = new Intl.DateTimeFormat("en-US", { timeZone: ET, weekday: "long" }).format(open);

  const windows: SetupWindowView[] = built.map(({ setup, label, state }) => ({ setup, label, state: weekend ? "later" : state }));

  if (!active.length) {
    return { phase: "done", headline: "Alerts are off.", detail: "No setup has a window.", windows };
  }
  if (weekend) {
    return {
      phase: "closed",
      headline: "Market is closed.",
      detail: `Next window is ${weekday}, ${span} Phoenix.`,
      windows,
    };
  }
  const clock = now.getTime();
  if (clock < first) {
    return { phase: "before", headline: `Alerts start at ${phoenixClock(new Date(first)).full} Phoenix.`, detail: `Window ${span} Phoenix.`, windows };
  }
  if (clock > last) {
    return { phase: "done", headline: "Alerts are done for the day.", detail: `The window was ${span} Phoenix.`, windows };
  }
  const inside = built.filter((w) => w.state === "open");
  if (inside.length) {
    return { phase: "open", headline: `Alerts can still fire until ${phoenixClock(new Date(last)).full} Phoenix.`, detail: `Window ${span} Phoenix.`, windows };
  }
  const upcoming = built.filter((w) => w.state === "later");
  const nextAt = Math.min(...upcoming.map((w) => w.first));
  const next = upcoming.filter((w) => w.first === nextAt);
  const sameLabel = next.every((w) => w.label === next[0].label);
  const who = joinSetups(next.map((w) => w.setup));
  const headline = sameLabel ? `${who} can fire ${next[0].label} Phoenix.` : `${who} can still fire.`;
  return { phase: "open", headline, detail: `Alerts finish at ${phoenixClock(new Date(last)).full} Phoenix.`, windows };
}

/** Lead sentence for an empty Today list. Null keeps the "no alerts yet" copy. */
export function todayEmptyLead(day: AlertDayStatus): string | null {
  if (day.phase === "done" || day.phase === "closed") return `${day.headline} ${day.detail}`;
  return null;
}

export const STATUS_LABEL: Record<AlertStatus, string> = {
  pending: "Pending",
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

/** Planned risk per share: trigger minus stop. */
export function riskPerShare(a: Pick<TradeAlert, "trigger_price" | "stop_price">): number {
  return a.trigger_price - a.stop_price;
}

/** Stop distance as a percent of the entry (trigger) price. */
export function stopPct(a: Pick<TradeAlert, "trigger_price" | "stop_price">): number {
  return a.trigger_price > 0 ? ((a.trigger_price - a.stop_price) / a.trigger_price) * 100 : 0;
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

export function notificationText(a: TradeAlert, setupName: string): { title: string; body: string } {
  return {
    title: `${a.symbol} setup ${a.setup}${a.top ? " (top)" : ""}`,
    body: `${setupName}. Buy stop ${a.trigger_price.toFixed(2)}, stop ${a.stop_price.toFixed(2)} (${stopPct(a).toFixed(2)}%). ${phoenixTime(a.fired_at)} Phoenix.`,
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

/** "+0.62%" distance of the setup bar's close from the 5-minute EMA 360; "—" when unknown (older alerts, thin history). */
export function ema360Text(a: Pick<TradeAlert, "details">): string {
  const v = a.details?.ema360_close_pct;
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/** Hover text: EMA level and both distances the not-extended filter checks. */
export function ema360Title(a: Pick<TradeAlert, "details">): string {
  const d = a.details ?? {};
  if (d.ema360 == null) return "5-minute EMA 360 not known for this alert";
  const pct = (v: number | null | undefined) => (v == null ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);
  return `5m EMA 360 (≈ 1h EMA 30) ${d.ema360.toFixed(2)}. Close ${pct(d.ema360_close_pct)}, last hour's low ${pct(d.ema360_low_pct)}`;
}

/** Tone for the distance cell: near the level is good, stretched is a warning. */
export function ema360Tone(a: Pick<TradeAlert, "details">, settings?: Record<string, number>): string {
  const c = a.details?.ema360_close_pct;
  if (c == null) return "";
  const max = settings?.ext_close_pct ?? 3;
  return c > max ? "red-text" : c <= 1 ? "green-text" : "";
}

/** Human labels and grouping for the settings form. */
export const SETTING_GROUPS: { title: string; items: [key: string, label: string, unit?: string][] }[] = [
  {
    title: "Bar and EMA definitions",
    items: [
      ["doji_body_pct", "Doji: body at most", "% of range"],
      ["doji_close_top_pct", "Doji: closes in the top", "% of range"],
      ["bunched_pct", "Bunched: 6/20/50 EMAs within", "%"],
      ["strong_close_top_pct", "Strong opening bar: closes in the top", "% of range"],
      ["tight_range_pct", "Tight bar: range at most", "% of opening bar"],
      ["gap_down_pct", "E: gap under the prior close, or low under the 20 and 50, by at least", "%"],
      ["touch_tol_pct", "D: touch / hold tolerance", "%"],
      ["d_lookback_bars", "D: pullback within the last", "bars"],
      ["f_bunched_minutes", "F: bunched and flat for at least", "minutes"],
      ["f_full_body_pct", "F: breakout body at least", "% of range"],
    ],
  },
  {
    title: "Filters and tracking",
    items: [
      ["vol_mult", "Setup bar volume at least", "x 20-session avg"],
      ["f_volume_mult", "F: breakout volume at least", "x avg"],
      ["vol_min_sessions", "Volume filter needs", "sessions of history"],
      ["max_stop_pct", "Skip when the stop is over", "% (A: cap)"],
      ["entry_valid_bars", "Buy stop good for", "bars"],
      ["max_attempts", "Triggered attempts per name per day", ""],
      ["breakeven_after_new_highs", "Stop to break-even after", "new-high bars"],
      ["top_names", "Top names per day", ""],
    ],
  },
  {
    title: "Not extended (5-minute EMA 360 ≈ 1-hour EMA 30)",
    items: [
      ["ext_filter", "Only alert near the EMA 360 (1 = on, 0 = off)", ""],
      ["ext_low_pct", "Last hour's low at most", "% over the EMA 360"],
      ["ext_close_pct", "Setup bar close at most", "% over the EMA 360"],
      ["ext_lookback_bars", "Last hour =", "bars (today only)"],
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
  {
    title: "Windows (minutes after the open; 0 = the opening bar)",
    items: [
      ["b_from", "B from", "min"],
      ["b_to", "B to", "min"],
      ["c_from", "C from", "min"],
      ["c_to", "C to", "min"],
      ["d_from", "D from", "min"],
      ["d_to", "D to", "min"],
      ["e_from", "E from", "min"],
      ["e_to", "E to", "min"],
      ["f_from", "F from", "min"],
      ["f_to", "F to", "min"],
    ],
  },
];
