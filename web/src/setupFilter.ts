/** Helpers for the weekly setup cell. (The old "Setup" dropdown is now the Candle Pattern filter, see candlePattern.ts.) */
export interface TriggerChip {
  label: string;
  title: string;
}

/**
 * The "triggered" chip next to a weekly setup, or null while it is still awaiting its trigger. A setup broken during
 * the week in progress says so; its trigger is still the last completed week's level.
 */
export function triggerChip(s: { triggered: boolean | null; live?: boolean | null; trigger?: number | null }): TriggerChip | null {
  if (!s.triggered) return null;
  const level = s.trigger != null ? ` ${s.trigger.toFixed(2)}` : "";
  if (s.live) {
    return { label: "triggered this week", title: `This week's high traded above the trigger${level} (set by last completed week)` };
  }
  return { label: "triggered", title: `Broke the trigger${level} on a completed week` };
}
