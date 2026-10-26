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
