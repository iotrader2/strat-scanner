import type { ScanRow } from "./api";

export type SetupFilter = "any" | "pending" | "triggered" | "inside" | "hammer";

type SetupFields = Pick<ScanRow, "trigger" | "triggered"> & { tf: Pick<ScanRow["tf"], "W"> };

/** Whether a scan row passes the Stock Scanner "Setup" filter. */
export function matchesSetup(r: SetupFields, filter: SetupFilter): boolean {
  switch (filter) {
    case "pending":
      return r.trigger !== null && !r.triggered;
    case "triggered":
      return r.triggered === true;
    case "inside":
      return !!r.tf.W?.inside;
    case "hammer":
      return !!r.tf.W?.hammer;
    default:
      return true;
  }
}

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
