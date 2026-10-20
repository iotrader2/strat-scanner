import { describe, expect, it } from "vitest";
import { SETUPS_FILTER_LABEL, SETUPS_OPTIONS } from "./pages/Scanner";

describe("Setups filter labels", () => {
  it("renames the filter group to Setups and drops that word from each item", () => {
    expect(SETUPS_FILTER_LABEL).toBe("Setups");
    const labels = SETUPS_OPTIONS.map((option) => option.label);
    expect(labels).toContain("Weekly strat awaiting trigger");
    expect(labels).toContain("Weekly strat already triggered");
    expect(labels).toContain("Daily bullish trend change");
    expect(labels).toContain("Daily bearish trend change");
    expect(labels).toContain("Weekly bullish trend change");
    expect(labels).toContain("Weekly bearish trend change");
    for (const label of labels) expect(label.toLowerCase()).not.toContain("setups");
  });

  it("maps the weekly Strat labels onto the existing awaiting and triggered filters", () => {
    expect(SETUPS_OPTIONS.find((option) => option.label === "Weekly strat awaiting trigger")?.value).toBe("setups_pending");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Weekly strat already triggered")?.value).toBe("setups_triggered");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Daily bullish trend change")?.value).toBe("daily_bullish");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Daily bearish trend change")?.value).toBe("daily_bearish");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Weekly bullish trend change")?.value).toBe("weekly_bullish");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Weekly bearish trend change")?.value).toBe("weekly_bearish");
  });
});
