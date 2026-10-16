import { describe, expect, it } from "vitest";
import { fmtPerf, isPerfSort, perfClass, perfSortValue, perfValue, PERF_PERIODS } from "./perf";
import { sortBy } from "./components/ScanTable";
import type { ScanRow } from "./api";

const row = (symbol: string, perf: Partial<ScanRow["perf"]>) =>
  ({ symbol, perf: { "1m": null, "3m": null, "6m": null, ...perf } }) as unknown as ScanRow;

describe("performance helpers", () => {
  it("lists the three periods in order", () => {
    expect(PERF_PERIODS.map((p) => p.label)).toEqual(["1M", "3M", "6M"]);
  });

  it("reads a period and treats a missing value as null", () => {
    expect(perfValue(row("A", { "3m": 12.5 }), "3m")).toBe(12.5);
    expect(perfValue(row("A", {}), "6m")).toBeNull();
    expect(perfValue({}, "1m")).toBeNull();
  });

  it("formats signed percentages with a true minus sign", () => {
    expect(fmtPerf(12.34)).toBe("+12.3%");
    expect(fmtPerf(-4)).toBe("−4.0%");
    expect(fmtPerf(0)).toBe("0.0%");
    expect(fmtPerf(null)).toBe("—");
    expect(fmtPerf(undefined)).toBe("—");
    expect(fmtPerf(5.678, 2)).toBe("+5.68%");
  });

  it("colours gains green and losses red", () => {
    expect(perfClass(0.1)).toBe("green-text");
    expect(perfClass(-0.1)).toBe("red-text");
    expect(perfClass(0)).toBe("muted");
    expect(perfClass(null)).toBe("muted");
  });

  it("recognises perf sort keys", () => {
    expect(isPerfSort("perf_3m")).toBe(true);
    expect(isPerfSort("perf_1y")).toBe(false);
    expect(isPerfSort("score")).toBe(false);
    expect(perfSortValue(row("A", { "6m": -3 }), "perf_6m")).toBe(-3);
  });

  it("sorts best or worst first and always puts unknown returns last", () => {
    const rows = [row("LOW", { "1m": -5 }), row("NA", {}), row("HIGH", { "1m": 20 }), row("MID", { "1m": 3 })];
    const value = (r: ScanRow) => perfSortValue(r, "perf_1m");
    expect(sortBy(rows, value, -1).map((r) => r.symbol)).toEqual(["HIGH", "MID", "LOW", "NA"]);
    expect(sortBy(rows, value, 1).map((r) => r.symbol)).toEqual(["LOW", "MID", "HIGH", "NA"]);
  });
});
