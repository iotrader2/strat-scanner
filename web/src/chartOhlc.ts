/** The O / H / L / C readout in the top-left corner of the candle charts (crosshair candle, else the latest). */

export interface OhlcBar {
  open: number;
  high: number;
  low: number;
  close: number;
}

/** Prices to the cent; sub-dollar prices to 4 decimals. */
export function fmtOhlcPrice(v: number): string {
  return Math.abs(v) < 1 ? v.toFixed(4) : v.toFixed(2);
}

/** Readout parts in display order: label, value, and whether the candle closed up. */
export function ohlcParts(bar: OhlcBar): { up: boolean; items: [string, string][] } {
  return {
    up: bar.close >= bar.open,
    items: [
      ["O", fmtOhlcPrice(bar.open)],
      ["H", fmtOhlcPrice(bar.high)],
      ["L", fmtOhlcPrice(bar.low)],
      ["C", fmtOhlcPrice(bar.close)],
    ],
  };
}

/** Write the readout into ``el`` (plain DOM: the crosshair moves too often for React state). */
export function renderOhlc(el: HTMLElement | null, bar: OhlcBar | null | undefined, when?: string): void {
  if (!el) return;
  el.replaceChildren();
  if (!bar) return;
  const { up, items } = ohlcParts(bar);
  if (when) {
    const t = document.createElement("span");
    t.className = "ohlc-when";
    t.textContent = when;
    el.appendChild(t);
  }
  for (const [k, v] of items) {
    const item = document.createElement("span");
    const key = document.createElement("b");
    key.textContent = k;
    const val = document.createElement("span");
    val.className = up ? "green-text" : "red-text";
    val.textContent = v;
    item.append(key, val);
    el.appendChild(item);
  }
}
