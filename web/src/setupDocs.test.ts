import { describe, expect, it } from "vitest";
import { fillParams, setupHint, setupLabel, type SetupDoc } from "./setupDocs";

const flat: SetupDoc = {
  kind: "flat-base-breakout",
  short_kind: "flat-base-breakdown",
  name: "Flat Base Breakout",
  short_name: "Flat Base Breakdown",
  rules: "Base: the last base_days days, no deeper than max_depth_pct.",
  entry: "Above the prior day's high.",
  stop: "Breakout-day low.",
  params: { base_days: 15, max_depth_pct: 10 },
};

describe("setup docs from setups.yaml", () => {
  it("puts the numbers into the rules text", () => {
    expect(fillParams(flat.rules, flat.params)).toBe("Base: the last 15 days, no deeper than 10%.");
    expect(fillParams("at least gap_day_min_gap_pct and min_volume_x", { min_gap_pct: 2, gap_day_min_gap_pct: 3, min_volume_x: 1.5 }))
      .toBe("at least 3% and 1.5x");
  });

  it("builds hover text and names for long and short options", () => {
    expect(setupHint("setup_flat_base", [flat])).toMatch(/last 15 days, no deeper than 10%\. Entry: Above the prior day's high\. Stop: Breakout-day low\./);
    expect(setupHint("short_flat_base", [flat])).toMatch(/Flat Base Breakout with the chart turned upside down/);
    expect(setupLabel("short_flat_base", [flat])).toBe("Flat Base Breakdown");
    expect(setupLabel("leaders", [flat])).toBeNull();
    expect(setupHint("setup_flat_base", undefined)).toBeNull();
  });
});
