import type { ScanRow } from "./api";
import { NO_SETUP_LABEL } from "./watchlist";

/** Leaders-only filter of the Stock Scanner: how strong the relative strength must be, and whether broken trends show. */
export type LeadershipFilter = "p90" | "p80" | "broken" | "all";

export const LEADER_RS = 0.9;
export const BROAD_RS = 0.8;

type LeaderFields = Pick<ScanRow, "rs"> & { leadership?: Pick<ScanRow["leadership"], "breakdown"> };

const rsAtLeast = (r: LeaderFields, min: number) => r.rs !== null && r.rs !== undefined && r.rs >= min;
const isBroken = (r: LeaderFields) => r.leadership?.breakdown === "broken";

/** Whether a scan row passes the Stock Scanner "Leadership" filter. Broken trends are never listed as leaders. */
export function matchesLeadership(r: LeaderFields, filter: LeadershipFilter): boolean {
  switch (filter) {
    case "p90":
      return rsAtLeast(r, LEADER_RS) && !isBroken(r);
    case "p80":
      return rsAtLeast(r, BROAD_RS) && !isBroken(r);
    case "broken":
      return rsAtLeast(r, BROAD_RS) && isBroken(r);
    default:
      return true;
  }
}

/** "P97" style label for a 0..1 relative-strength percentile. */
export function fmtRs(rs: number | null | undefined): string {
  return rs === null || rs === undefined ? "—" : `P${Math.round(rs * 100)}`;
}

export interface TriggerHint {
  price: number;
  distancePct: number;
  label: string;
}

/** The trigger to show for a row: its weekly setup's, or for a name with no setup the nearest weekly high above price. */
export function triggerHint(
  r: Pick<ScanRow, "trigger" | "trigger_distance_pct" | "nearest_trigger" | "nearest_trigger_distance_pct" | "nearest_trigger_label">,
): (TriggerHint & { nearest: boolean }) | null {
  if (r.trigger !== null && r.trigger !== undefined) {
    return { price: r.trigger, distancePct: r.trigger_distance_pct ?? 0, label: "setup trigger", nearest: false };
  }
  if (r.nearest_trigger !== null && r.nearest_trigger !== undefined) {
    return {
      price: r.nearest_trigger,
      distancePct: r.nearest_trigger_distance_pct ?? 0,
      label: r.nearest_trigger_label ?? "nearest weekly high",
      nearest: true,
    };
  }
  return null;
}

export const NO_SETUP_LEADER = "No setup / leader";

/** Label for the setup cell of a row without a weekly setup. */
export function noSetupLabel(r: LeaderFields): string {
  return rsAtLeast(r, LEADER_RS) && !isBroken(r) ? NO_SETUP_LEADER : NO_SETUP_LABEL;
}
