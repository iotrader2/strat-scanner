import { describe, expect, it } from "vitest";
import { earningsLines } from "./earnings";

describe("earnings caution tooltip", () => {
  it("shows the date with BMO / AMC timing and a countdown", () => {
    expect(earningsLines({ date: "2026-10-21", date_end: null, timing: "AMC", days_until: 6 })).toEqual([
      "Earnings Wed, Oct 21",
      "AMC (after close) · in 6 days",
    ]);
    expect(earningsLines({ date: "2026-10-16", date_end: null, timing: "BMO", days_until: 1 })).toEqual([
      "Earnings Fri, Oct 16",
      "BMO (before open) · tomorrow",
    ]);
  });

  it("says time TBD when the timing is unknown", () => {
    expect(earningsLines({ date: "2026-10-15", date_end: null, timing: null, days_until: 0 })[1]).toBe("time TBD · today");
  });

  it("labels Yahoo's estimated ranges as such", () => {
    expect(earningsLines({ date: "2026-10-22", date_end: "2026-10-27", timing: null, days_until: 7 })[0]).toBe(
      "Earnings Thu, Oct 22 – Tue, Oct 27 (estimated range)",
    );
  });
});
