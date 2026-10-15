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
