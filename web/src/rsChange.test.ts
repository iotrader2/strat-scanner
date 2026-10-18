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

  it("marks a breakdown that just worsened, with the word shown on the chip", () => {
    expect(newMarker(row(0.9, {}, { breakdown: "warning", breakdown_new: worsened }))).toEqual({ kind: "warning", label: "weakening", since: "2026-10-16" });
    expect(newMarker(row(0.9, {}, { breakdown: "broken", breakdown_new: { ...worsened, from: "warning", to: "broken" } }))).toEqual({
      kind: "broken",
      label: "broken",
      since: "2026-10-16",
    });
  });

  it("marks a newly entered leader, after a worsening", () => {
    const entry = { since: "2026-10-15", sessions_ago: 1, from_rs: 0.88 };
    expect(newMarker(row(0.92, {}, { leader_new: entry }))).toEqual({ kind: "leader", label: "leader", since: "2026-10-15" });
    expect(newMarker(row(0.92, {}, { breakdown: "warning", breakdown_new: worsened, leader_new: entry }))?.kind).toBe("warning");
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

  it("shows RS, the change arrow and the usual flag", () => {
    const v = rsChipView(row(0.914, { rs_prev: 0.984, rs_prev_date: "2026-10-09", rs_change: -7 }, { breakdown: "warning" }))!;
    expect(v.rs).toBe(91);
    expect(v.delta?.text).toBe("▼7");
    expect(v.flag).toBe("weakening");
    expect(v.level).toBe("warning");
    expect(v.newMarker).toBeNull();
  });

  it("drops the duplicate flag when the NEW marker already says it", () => {
    const v = rsChipView(
      row(0.93, {}, { breakdown: "broken", breakdown_new: { from: "warning", to: "broken", since: "2026-10-16", sessions_ago: 0 } }),
    )!;
    expect(v.newMarker?.label).toBe("broken");
    expect(v.flag).toBe("");
  });

  it("keeps a standing weakening flag next to a newly entered leader", () => {
    const v = rsChipView(row(0.93, {}, { breakdown: "warning", leader_new: { since: "2026-10-16", sessions_ago: 0, from_rs: 0.8 } }))!;
    expect(v.newMarker?.kind).toBe("leader");
    expect(v.flag).toBe("weakening");
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

  it("dates a NEW breakdown and a NEW leader", () => {
    const warn = rsTitle(
      row(0.9, {}, { breakdown: "warning", breakdown_new: { from: "none", to: "warning", since: "2026-10-15", sessions_ago: 1 } }),
    );
    expect(warn).toContain("NEW weakening: changed on 2026-10-15 (1 session ago), from no breakdown flag.");
    const broken = rsTitle(
      row(0.9, {}, { breakdown: "broken", breakdown_new: { from: "warning", to: "broken", since: "2026-10-16", sessions_ago: 0 } }),
    );
    expect(broken).toContain("NEW broken: changed on 2026-10-16 (today), from weakening.");
    const lead = rsTitle(row(0.92, {}, { leader_new: { since: "2026-10-14", sessions_ago: 2, from_rs: 0.886 } }));
    expect(lead).toContain("NEW leader: RS crossed above P90 on 2026-10-14 (2 sessions ago), from P89.");
  });

  it("has no change lines when the backend sent none", () => {
    expect(rsTitle(row(0.9)).split("\n")).toHaveLength(1);
  });
});
