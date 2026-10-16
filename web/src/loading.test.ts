import { describe, expect, it } from "vitest";
import { refreshProgress } from "./loading";

describe("refreshProgress", () => {
  it("shows done/total and the current step while downloading", () => {
    expect(refreshProgress({ done: 120, total: 546, message: "Downloading AAPL…AMD (5d)" })).toEqual({
      label: "Refreshing data… 120/546",
      detail: "Downloading AAPL…AMD (5d)",
      pct: 22,
    });
  });

  it("is indeterminate before the total is known", () => {
    expect(refreshProgress({ done: 0, total: 0, message: "Starting" })).toEqual({
      label: "Refreshing data… starting",
      detail: null,
      pct: null,
    });
  });

  it("names the earnings stage instead of repeating its count", () => {
    expect(refreshProgress({ done: 40, total: 518, message: "Earnings dates 40/518" })).toEqual({
      label: "Refreshing earnings dates… 40/518",
      detail: null,
      pct: 8,
    });
  });

  it("clamps out-of-range counts", () => {
    expect(refreshProgress({ done: 600, total: 546, message: "Done" }).label).toBe("Refreshing data… 546/546");
    expect(refreshProgress({ done: 600, total: 546, message: "Done" }).pct).toBe(100);
    expect(refreshProgress({ done: -1, total: 10, message: "" }).pct).toBe(0);
  });
});
