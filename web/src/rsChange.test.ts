import { describe, expect, it } from "vitest";
import type { ScanRow } from "./api";
import { RS_CHANGE_MIN, newMarker, rsChipView, rsDelta, rsTitle } from "./rsChange";

type Lead = Partial<ScanRow["leadership"]>;
const row = (rs: number | null, extra: Partial<ScanRow> = {}, lead: Lead = {}) =>
  ({
    rs,
    rs_prev: null,
    rs_prev_date: null,
    rs_change: null,
    kill_candle: null,
    leadership: { breakdown: "none", breakdown_reasons: [], breakdown_new: null, leader_new: null, ...lead },
    ...extra,
  }) as unknown as ScanRow;

describe("rsDelta", () => {
  it("shows drops as a red-down arrow and rises as a green-up arrow", () => {
    expect(rsDelta({ rs_change: -7 })).toEqual({ points: -7, dir: "down", text: "▼7" });
    expect(rsDelta({ rs_change: 12 })).toEqual({ points: 12, dir: "up", text: "▲12" });
  });

  it("hides changes smaller than 3 points and unknown ones", () => {
    expect(RS_CHANGE_MIN).toBe(3);
    expect(rsDelta({ rs_change: 2 })).toBeNull();
    expect(rsDelta({ rs_change: -2 })).toBeNull();
    expect(rsDelta({ rs_change: 0 })).toBeNull();
    expect(rsDelta({ rs_change: 3 })?.text).toBe("▲3");
    expect(rsDelta({ rs_change: -3 })?.text).toBe("▼3");
    expect(rsDelta({ rs_change: null })).toBeNull();
    expect(rsDelta({})).toBeNull();
  });
});

describe("newMarker", () => {
  const worsened = { from: "none", to: "warning", since: "2026-10-16", sessions_ago: 0 } as const;

  it("marks a trend that just broke, and skips a warning", () => {
    expect(newMarker(row(0.9, {}, { breakdown: "warning", breakdown_new: worsened }))).toBeNull();
    expect(newMarker(row(0.9, {}, { breakdown: "broken", breakdown_new: { ...worsened, from: "warning", to: "broken" } }))).toEqual({
      kind: "broken",
      label: "broken",
      since: "2026-10-16",
    });
  });

  it("marks a newly entered leader, including one that only has a warning", () => {
    const entry = { since: "2026-10-15", sessions_ago: 1, from_rs: 0.88 };
    expect(newMarker(row(0.92, {}, { leader_new: entry }))).toEqual({ kind: "leader", label: "leader", since: "2026-10-15" });
    expect(newMarker(row(0.92, {}, { breakdown: "warning", breakdown_new: worsened, leader_new: entry }))?.kind).toBe("leader");
    expect(newMarker(row(0.92, {}, { breakdown: "broken", breakdown_new: { ...worsened, to: "broken" }, leader_new: entry }))?.kind).toBe("broken");
  });

  it("has nothing for a row without transitions or without the fields", () => {
    expect(newMarker(row(0.9))).toBeNull();
    expect(newMarker({ leadership: { breakdown: "none" } })).toBeNull();
    expect(newMarker({})).toBeNull();
  });
});

describe("rsChipView", () => {
  it("has no chip without RS", () => {
    expect(rsChipView(row(null))).toBeNull();
  });

  it("shows the change arrow and leaves a warning unbadged, even when RS is rising", () => {
    const down = rsChipView(row(0.914, { rs_prev: 0.984, rs_prev_date: "2026-10-09", rs_change: -7 }, { breakdown: "warning" }))!;
    expect(down).not.toHaveProperty("rs");
    expect(down.title).toContain("Relative strength P91");
    expect(down.delta?.text).toBe("▼7");
    expect(down.flag).toBe("");
    expect(down.level).toBe("none");
    expect(down.newMarker).toBeNull();
    expect(down.title).not.toContain("weakening");

    const up = rsChipView(row(0.95, { rs_prev: 0.83, rs_prev_date: "2026-10-09", rs_change: 12 }, { breakdown: "warning" }))!;
    expect(up.delta).toEqual({ points: 12, dir: "up", text: "▲12" });
    expect(up.flag).toBe("");
    expect(up.level).toBe("none");
    expect(up.title).not.toContain("weakening");
  });

  it("has no arrow under 3 points but keeps both readings in the title", () => {
    const v = rsChipView(row(0.92, { rs_prev: 0.9, rs_prev_date: "2026-10-09", rs_change: 2 }))!;
    expect(v.delta).toBeNull();
    expect(v.title).toContain("P90 on 2026-10-09 → P92");
  });

  it("drops the duplicate flag when the NEW marker already says it", () => {
    const v = rsChipView(
      row(0.93, {}, { breakdown: "broken", breakdown_new: { from: "warning", to: "broken", since: "2026-10-16", sessions_ago: 0 } }),
    )!;
    expect(v.newMarker?.label).toBe("broken");
    expect(v.flag).toBe("");
  });

  it("shows a newly entered leader without a weakening flag", () => {
    const v = rsChipView(row(0.93, { rs_change: 8 }, { breakdown: "warning", leader_new: { since: "2026-10-16", sessions_ago: 0, from_rs: 0.8 } }))!;
    expect(v.newMarker?.kind).toBe("leader");
    expect(v.delta?.text).toBe("▲8");
    expect(v.flag).toBe("");
    expect(v.level).toBe("none");
  });

  it("appends the kill candle date", () => {
    const kill = { date: "2026-10-12", penalty: 0.1 } as ScanRow["kill_candle"];
    expect(rsChipView(row(0.9, { kill_candle: kill }))!.kill).toBe(" · kill candle 10-12");
    expect(rsChipView(row(0.9, { kill_candle: { ...kill!, penalty: 0 } }))!.kill).toBe("");
  });
});

describe("rsTitle", () => {
  it("keeps the original first line with the breakdown reasons", () => {
    expect(rsTitle(row(0.914, {}, { breakdown_reasons: ["below the 20-day average"] }))).toBe(
      "Relative strength P91: blended 1M/3M/6M return percentile. below the 20-day average",
    );
  });

  it("adds the RS change with both readings and the date", () => {
    const t = rsTitle(row(0.914, { rs_prev: 0.984, rs_prev_date: "2026-10-09", rs_change: -7 }));
    expect(t).toContain("RS change vs 5 sessions ago: P98 on 2026-10-09 → P91 (▼7)");
  });

  it("explains small changes that the chip hides", () => {
    expect(rsTitle(row(0.92, { rs_prev: 0.9, rs_prev_date: "2026-10-09", rs_change: 2 }))).toContain("(+2, under 3 points so not shown)");
    expect(rsTitle(row(0.9, { rs_prev: 0.9, rs_prev_date: "2026-10-09", rs_change: 0 }))).toContain("(unchanged)");
  });

  it("dates a NEW break and a NEW leader, and skips a warning", () => {
    const warn = rsTitle(
      row(0.9, {}, { breakdown: "warning", breakdown_new: { from: "none", to: "warning", since: "2026-10-15", sessions_ago: 1 } }),
    );
    expect(warn).not.toContain("weakening");
    expect(warn).not.toContain("NEW");
    const broken = rsTitle(
      row(0.9, {}, { breakdown: "broken", breakdown_new: { from: "warning", to: "broken", since: "2026-10-16", sessions_ago: 0 } }),
    );
    expect(broken).toContain("NEW broken: changed on 2026-10-16 (today), from a trend warning.");
    expect(broken).not.toContain("weakening");
    const lead = rsTitle(row(0.92, {}, { leader_new: { since: "2026-10-14", sessions_ago: 2, from_rs: 0.886 } }));
    expect(lead).toContain("NEW leader: RS crossed above P90 on 2026-10-14 (2 sessions ago), from P89.");
  });

  it("has no change lines when the backend sent none", () => {
    expect(rsTitle(row(0.9)).split("\n")).toHaveLength(1);
  });
});
