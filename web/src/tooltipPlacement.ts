/** Where to put a floating tooltip next to an anchor so it stays inside the viewport. */

export interface Rect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface Size {
  width: number;
  height: number;
}

export const TOOLTIP_MARGIN = 12; // minimum gap to every viewport edge
export const TOOLTIP_GAP = 8; // gap between the anchor and the tooltip

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, Math.max(lo, hi)));

/**
 * Top-left corner (viewport px) for a tooltip of ``size`` beside ``anchor``.
 *
 * Horizontally it prefers to end at the anchor's right edge (it opens leftwards over the row), and opens rightwards
 * from the anchor's left edge when that would cross the left edge (first-column pills). Vertically it goes below the
 * anchor, or above when there is no room below, or wherever there is more room. Either way it is clamped so all four
 * edges stay at least ``margin`` inside the viewport (a tooltip larger than the viewport sticks to the top/left margin).
 */
export function placeTooltip(
  anchor: Rect,
  size: Size,
  viewport: Size,
  margin = TOOLTIP_MARGIN,
  gap = TOOLTIP_GAP,
): { left: number; top: number; above: boolean } {
  let left = anchor.right - size.width;
  if (left < margin) left = anchor.left;
  left = clamp(left, margin, viewport.width - margin - size.width);

  const below = anchor.bottom + gap;
  const aboveTop = anchor.top - gap - size.height;
  const fitsBelow = below + size.height <= viewport.height - margin;
  const fitsAbove = aboveTop >= margin;
  const above = !fitsBelow && (fitsAbove || anchor.top > viewport.height - anchor.bottom);
  const top = clamp(above ? aboveTop : below, margin, viewport.height - margin - size.height);
  return { left, top, above };
}
