import type { Perf, PerfPeriod, ScanRow } from "./api";

export const PERF_PERIODS: { key: PerfPeriod; label: string }[] = [
  { key: "1m", label: "1M" },
  { key: "3m", label: "3M" },
  { key: "6m", label: "6M" },
];

/** A row's price return (percent) for a period, or null when the history is too short. */
export function perfValue(row: { perf?: Perf | null }, period: PerfPeriod): number | null {
  return row.perf?.[period] ?? null;
}

/** "+12.3%" / "−4.0%" with a true minus sign, or an em dash when unknown. */
export function fmtPerf(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (v === 0) return `${(0).toFixed(digits)}%`;
  return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}%`;
}

/** CSS class for the green/red colouring ("" for zero or unknown). */
export function perfClass(v: number | null | undefined): "green-text" | "red-text" | "muted" {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return "muted";
  return v > 0 ? "green-text" : "red-text";
}

export type PerfSort = `perf_${PerfPeriod}`;

export function isPerfSort(key: string): key is PerfSort {
  return PERF_PERIODS.some((p) => `perf_${p.key}` === key);
}

export function perfSortValue(row: Pick<ScanRow, "perf">, key: PerfSort): number | null {
  return perfValue(row, key.slice(5) as PerfPeriod);
}
