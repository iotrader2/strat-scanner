import type { ScanRow } from "./api";

/**
 * ATR % filter of the Stock Scanner: the 14-day average true range as a percent of the last close
 * (`atr_pct` on the scan row, the same ATR the backend computes for every row). The top of the slider
 * means "no upper limit", so the default full range filters nothing.
 */
export const ATR_PCT_RANGE = { min: 0, max: 12, step: 0.25 } as const;

export type AtrRange = readonly [number, number];

export const ATR_PCT_DEFAULT: AtrRange = [ATR_PCT_RANGE.min, ATR_PCT_RANGE.max];

/** ATR as a percent of price, the way the backend rounds it (null without a usable price or ATR). */
export function atrPercent(atr: number | null | undefined, price: number | null | undefined): number | null {
  if (atr == null || price == null || !Number.isFinite(atr) || !Number.isFinite(price) || price <= 0 || atr < 0) {
    return null;
  }
  return Math.round((atr / price) * 100 * 100) / 100;
}

const snap = (v: number): number => {
  const stepped = Math.round(v / ATR_PCT_RANGE.step) * ATR_PCT_RANGE.step;
  return Math.min(ATR_PCT_RANGE.max, Math.max(ATR_PCT_RANGE.min, stepped));
};

/** A saved or dragged range, clamped to the slider, snapped to its step and ordered low to high. */
export function normalizeAtrRange(saved: unknown): AtrRange {
  if (!Array.isArray(saved) || saved.length !== 2) return ATR_PCT_DEFAULT;
  const [a, b] = saved.map(Number);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return ATR_PCT_DEFAULT;
  const lo = snap(Math.min(a, b));
  const hi = snap(Math.max(a, b));
  return [lo, hi];
}

export function isAtrFilterActive(range: AtrRange): boolean {
  return range[0] > ATR_PCT_RANGE.min || range[1] < ATR_PCT_RANGE.max;
}

/** Whether a row's ATR % is inside the range. The full range keeps every row, including rows without ATR. */
export function passesAtr(row: Pick<ScanRow, "atr_pct">, range: AtrRange): boolean {
  if (!isAtrFilterActive(range)) return true;
  const pct = row.atr_pct;
  if (pct == null || !Number.isFinite(pct)) return false;
  if (pct < range[0]) return false;
  return range[1] >= ATR_PCT_RANGE.max || pct <= range[1];
}

/** Readout for the slider head: "Any", "≥ 2%", "≤ 6%" or "2% – 6%". */
export function formatAtrRange(range: AtrRange): string {
  const pct = (v: number) => `${Number.isInteger(v) ? v : v.toFixed(2).replace(/0$/, "")}%`;
  const lowSet = range[0] > ATR_PCT_RANGE.min;
  const highSet = range[1] < ATR_PCT_RANGE.max;
  if (lowSet && highSet) return `${pct(range[0])} – ${pct(range[1])}`;
  if (lowSet) return `≥ ${pct(range[0])}`;
  if (highSet) return `≤ ${pct(range[1])}`;
  return "Any";
}
