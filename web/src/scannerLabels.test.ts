import { describe, expect, it } from "vitest";
import { SETUPS_FILTER_LABEL, SETUPS_OPTIONS } from "./pages/Scanner";

describe("Setups filter labels", () => {
  it("renames the filter group to Setups and drops that word from each item", () => {
    expect(SETUPS_FILTER_LABEL).toBe("Setups");
    const labels = SETUPS_OPTIONS.map((option) => option.label);
    for (const name of ["Episodic Pivot", "Delayed High Volume Close", "Flat Base Breakout", "Undercut and Rally", "MA Undercut and Rally", "High Tight Flag"]) {
      expect(labels).toContain(name);
    }
    expect(labels).toContain("Daily bullish trend change");
    expect(labels).toContain("Daily bearish trend change");
    expect(labels).toContain("Weekly bullish trend change");
    expect(labels).toContain("Weekly bearish trend change");
    for (const label of labels) expect(label.toLowerCase()).not.toContain("setups");
  });

  it("maps each setup label to its own filter and keeps the trend changes", () => {
    expect(SETUPS_OPTIONS.find((option) => option.label === "Episodic Pivot")?.value).toBe("setup_ep");
    expect(SETUPS_OPTIONS.find((option) => option.label === "High Tight Flag")?.value).toBe("setup_htf");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Daily bullish trend change")?.value).toBe("daily_bullish");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Daily bearish trend change")?.value).toBe("daily_bearish");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Weekly bullish trend change")?.value).toBe("weekly_bullish");
    expect(SETUPS_OPTIONS.find((option) => option.label === "Weekly bearish trend change")?.value).toBe("weekly_bearish");
  });
});
