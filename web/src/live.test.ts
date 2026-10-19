import { describe, expect, it } from "vitest";
import { formatLocal, liveStatus } from "./live";
import type { Status } from "./api";

function status(over: Partial<Status> = {}): Status {
  return {
    last_refresh: "2026-10-16T19:45:00Z",
    as_of: null,
    refreshing: false,
    updating: false,
    progress: { done: 0, total: 0, message: "" },
    error: null,
    symbols_cached: 646,
    universe_size: 646,
    version: 2,
    computed_at: "2026-10-16T19:45:00Z",
    delay: "15m",
    ...over,
  };
}

describe("liveStatus", () => {
  it("says connecting until the socket opens", () => {
    expect(liveStatus(null, "connecting")).toEqual({ tone: "off", label: "Connecting" });
    expect(liveStatus(status(), "reconnecting").label).toBe("Reconnecting");
  });

  it("shows a cut-off view without a live clock", () => {
    expect(liveStatus(status({ as_of: "2026-08-13" }), "open")).toEqual({
      tone: "stale",
      label: "Cut-off view, data through 2026-08-13",
    });
  });

  it("shows how many symbols the fetcher has reached", () => {
    expect(
      liveStatus(status({ updating: true, refreshing: true, progress: { done: 80, total: 646, message: "" } }), "open"),
    ).toEqual({ tone: "busy", label: "Updating · 80/646 symbols" });
  });

  it("labels a settled scan as 15-minute delayed, in the browser timezone", () => {
    const view = liveStatus(status(), "open");
    const local = new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(new Date("2026-10-16T19:45:00Z"));
    expect(view.tone).toBe("live");
    expect(formatLocal("2026-10-16T19:45:00Z")).toBe(local);
    expect(view.label).toBe(`15-min delayed · updated ${local}`);
    expect(view.label).not.toMatch(/ ET$/);
  });
});
