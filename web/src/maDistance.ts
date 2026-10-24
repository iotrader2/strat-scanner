import type { ScanRow } from "./api";

/** The daily simple averages every chart draws. */
export const MA_DISTANCE_PERIODS = [6, 20, 50] as const;
export type MaPeriod = (typeof MA_DISTANCE_PERIODS)[number];

/**
 * Percent distance of price from the daily N SMA, `(price - SMA) / SMA * 100`, as computed by the backend
 * (`ma_dist_pct` on the scan row); null when unavailable. A variant (e.g. net of ATR %) would be another reader here
 * feeding the same formatter.
 */
export function maDistance(row: Pick<ScanRow, "ma_dist_pct">, period: MaPeriod): number | null {
  const v = row.ma_dist_pct?.[String(period) as `${MaPeriod}`];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export const maSortKey = (period: MaPeriod) => `ma_dist_${period}`;
export const maLabel = (period: MaPeriod) => `vs ${period} MA`;
export const maTitle = (period: MaPeriod) => `Percent distance of price from the daily ${period} SMA; 0% = on the average`;

const tenth = (v: number) => Math.round(v * 10) / 10;

/** The one place the distance is formatted: signed, one decimal, percent ("+3.0%", "-0.2%", "0.0%"), em dash when missing. */
export function fmtMaDistance(v: number | null): string {
  if (v === null) return "—";
  const shown = tenth(v);
  if (shown === 0) return "0.0%";
  return `${shown > 0 ? "+" : "-"}${Math.abs(shown).toFixed(1)}%`;
}

/** Green above the average, red below, neutral when it rounds to 0.0% or is missing. */
export function maDistanceTone(v: number | null): "green-text" | "red-text" | "muted" {
  if (v === null) return "muted";
  const shown = tenth(v);
  return shown > 0 ? "green-text" : shown < 0 ? "red-text" : "muted";
}

export const maMissingTitle = (period: MaPeriod) => `Not enough daily bars for the ${period} SMA`;
