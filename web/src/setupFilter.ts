/** Helpers for the daily setup cell. (The old "Setup" dropdown is now the Candle Pattern filter, see candlePattern.ts.) */
export interface TriggerChip {
  label: string;
  title: string;
}

/**
 * The "triggered" chip next to a daily setup, or null while it is still awaiting its trigger. A setup broken during
 * today's session says so; its trigger is still the last completed day's level.
 */
export function triggerChip(s: {
  triggered: boolean | null;
  live?: boolean | null;
  trigger?: number | null;
  side?: "long" | "short" | null;
}): TriggerChip | null {
  if (!s.triggered) return null;
  const level = s.trigger != null ? ` ${s.trigger.toFixed(2)}` : "";
  if (s.live) {
    const how = s.side === "short" ? "Today's low traded below" : "Today's high traded above";
    return { label: "triggered today", title: `${how} the trigger${level} (set by last completed day)` };
  }
  return { label: "triggered", title: `Broke the trigger${level} on a completed day` };
}
