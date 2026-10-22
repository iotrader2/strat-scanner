import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TfState } from "../api";
import { TfBadge, badgeContinuity } from "./Badges";

const completedRedWeek: TfState = {
  tf: "W",
  strat: "2D",
  prev_strat: "2U",
  color: "red",
  open: 208.97,
  high: 214,
  low: 205,
  close: 207.82,
  inside: false,
  hammer: false,
};

describe("TfBadge continuity color", () => {
  it("colors by the bar in progress when the scan sends it", () => {
    const live = { ...completedRedWeek, live_color: "green" as const, live_open: 208.11 };
    expect(badgeContinuity(live)).toEqual({ color: "green", open: 208.11, live: true });
    const html = renderToStaticMarkup(<TfBadge tf="W" state={live} />);
    expect(html).toContain('class="tf-badge green s2d"');
    expect(html).toContain("green vs open 208.11 (bar in progress)");
    // The Strat label is still the last completed week's.
    expect(html).toContain("DOWN");
  });

  it("falls back to the completed bar without live fields (3M / 6M, older payloads)", () => {
    expect(badgeContinuity(completedRedWeek)).toEqual({ color: "red", open: 208.97, live: false });
    expect(renderToStaticMarkup(<TfBadge tf="W" state={completedRedWeek} />)).toContain('class="tf-badge red s2d"');
  });
});
