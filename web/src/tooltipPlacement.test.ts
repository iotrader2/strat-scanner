import { describe, expect, it } from "vitest";
import { placeTooltip, TOOLTIP_MARGIN } from "./tooltipPlacement";

const VIEW = { width: 1440, height: 1000 };
const SIZE = { width: 380, height: 444 };
const rect = (left: number, top: number, w = 38, h = 23) => ({ left, top, right: left + w, bottom: top + h });

function inside(p: { left: number; top: number }, size = SIZE, view = VIEW) {
  expect(p.left).toBeGreaterThanOrEqual(TOOLTIP_MARGIN);
  expect(p.top).toBeGreaterThanOrEqual(TOOLTIP_MARGIN);
  expect(p.left + size.width).toBeLessThanOrEqual(view.width - TOOLTIP_MARGIN);
  expect(p.top + size.height).toBeLessThanOrEqual(view.height - TOOLTIP_MARGIN);
}

describe("placeTooltip", () => {
  it("opens leftwards from a pill in the middle of the row, below it", () => {
    const p = placeTooltip(rect(800, 200), SIZE, VIEW);
    expect(p).toEqual({ left: 838 - 380, top: 231, above: false });
  });

  it("opens rightwards for a first-column pill instead of running off the left edge", () => {
    // The scanner's score pill sits at x=43; the old code put the tooltip at x=-299.
    const p = placeTooltip(rect(43, 200), SIZE, VIEW);
    expect(p.left).toBe(43);
    inside(p);
  });

  it("flips above near the bottom and stays inside the viewport", () => {
    const p = placeTooltip(rect(43, 897), SIZE, VIEW);
    expect(p.above).toBe(true);
    expect(p.top).toBe(897 - 8 - 444);
    inside(p);
  });

  it("clamps at the right edge and when neither side fits vertically", () => {
    const small = { width: 1440, height: 600 };
    const p = placeTooltip(rect(1420, 280, 30, 23), SIZE, small);
    inside(p, SIZE, small);
  });

  it("sticks to the margin when the tooltip is wider than a narrow viewport", () => {
    const phone = { width: 360, height: 700 };
    const p = placeTooltip(rect(20, 100), SIZE, phone);
    expect(p.left).toBe(TOOLTIP_MARGIN);
  });
});
