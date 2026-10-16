export const SLIDER_STEPS = 1000;

/** Map a slider position (0..SLIDER_STEPS) onto [min, max] on a log scale. */
export function sliderToValue(pos: number, min: number, max: number): number {
  const t = Math.min(Math.max(pos, 0), SLIDER_STEPS) / SLIDER_STEPS;
  return Math.exp(Math.log(min) + t * (Math.log(max) - Math.log(min)));
}

/** Inverse of sliderToValue; values outside [min, max] are clamped. */
export function valueToSlider(value: number, min: number, max: number): number {
  const v = Math.min(Math.max(value, min), max);
  return Math.round(((Math.log(v) - Math.log(min)) / (Math.log(max) - Math.log(min))) * SLIDER_STEPS);
}

/** Round to 2 significant digits so slider values read cleanly (2.5M, 140K, 50M). */
export function niceRound(value: number): number {
  if (value <= 0) return 0;
  const exp = Math.floor(Math.log10(value)) - 1;
  // Divide by the inverse for small magnitudes so 1.2 stays 1.2 rather than 1.2000000000000002.
  return exp < 0 ? Math.round(value * 10 ** -exp) / 10 ** -exp : Math.round(value / 10 ** exp) * 10 ** exp;
}

export function fmtCompact(value: number): string {
  const units: [number, string][] = [
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [size, suffix] of units) {
    if (value >= size) {
      const n = value / size;
      const text = n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1).replace(/\.0$/, "") : n.toFixed(2).replace(/\.?0+$/, "");
      return `${text}${suffix}`;
    }
  }
  return value.toFixed(0);
}

/** Dollar price for slider readouts: "$1.5", "$10", "$450", "$1,000". */
export function fmtPrice(value: number): string {
  return `$${Number(value.toFixed(2)).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

export interface LiquidityFilter {
  minPrice: number;
  minDollarVolume: number;
}

export function passesLiquidity(
  row: { price: number; avg_dollar_volume: number },
  f: LiquidityFilter,
): boolean {
  return row.price >= f.minPrice && row.avg_dollar_volume >= f.minDollarVolume;
}

/**
 * Slider position to show for `value`. Keeps `currentPos` while it still rounds to `value`, so
 * small steps near the ends are not snapped back by niceRound.
 */
export function syncSliderPosition(value: number, min: number, max: number, currentPos: number): number {
  return sliderValue(currentPos, min, max) === value ? currentPos : valueToSlider(value, min, max);
}

/** Value emitted for a slider position: exact at the ends, 2 significant digits in between. */
export function sliderValue(pos: number, min: number, max: number): number {
  if (pos <= 0) return min;
  if (pos >= SLIDER_STEPS) return max;
  return niceRound(sliderToValue(pos, min, max));
}
