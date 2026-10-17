import { describe, expect, it } from "vitest";
import type { ScanRow } from "./api";
import {
  BREAKOUT_MIN_RS,
  LEADER_RS,
  MIN_RS_RANGE,
  NO_SETUP_LEADER,
  breakoutLabel,
  fmtRs,
  formatWeight,
  matchesLeadership,
  migrateLeadership,
  noSetupLabel,
  sliderToRs,
  triggerHint,
  type LeadershipFilter,
} from "./leadership";
import { readPersisted, writePersisted } from "./persist";

type Breakout = NonNullable<ScanRow["breakout"]>;
const breakoutInfo: Breakout = {
  week: "2026-09-14",
  base_weeks: 6,
  base_high: 100,
  close: 106,
  volume_x: 2.1,
  close_position: 0.9,
} as Breakout;

const row = (rs: number | null, breakdown: "none" | "warning" | "broken" = "none", breakout: Breakout | null = null) => ({
  rs,
  leadership: { breakdown },
  breakout,
});

const leader = row(0.97);
const weakening = row(0.93, "warning");
const midLeader = row(0.85);
const brokenLeader = row(0.96, "broken");
const brokenMid = row(0.82, "broken");
const laggard = row(0.4);
const noHistory = row(null);
const midBreakout = row(0.62, "none", breakoutInfo);
const weakBreakout = row(0.3, "none", breakoutInfo);
const brokenBreakout = row(0.7, "broken", breakoutInfo);
const rows = [leader, weakening, midLeader, brokenLeader, brokenMid, laggard, noHistory, midBreakout, weakBreakout, brokenBreakout];
const pick = (f: LeadershipFilter, minRs?: number) => rows.filter((r) => matchesLeadership(r, f, minRs));

describe("matchesLeadership", () => {
  it("Leaders defaults to P90 and never lists a broken trend", () => {
    expect(LEADER_RS).toBe(0.9);
    expect(MIN_RS_RANGE).toEqual({ min: 50, max: 99, default: 90 });
    expect(pick("leaders")).toEqual([leader, weakening]);
  });

  it("the Min RS slider moves the Leaders cut", () => {
    expect(pick("leaders", sliderToRs(80))).toEqual([leader, weakening, midLeader]);
    expect(pick("leaders", sliderToRs(97))).toEqual([leader]);
    expect(pick("leaders", sliderToRs(60))).toEqual([leader, weakening, midLeader, midBreakout]);
  });

  it("the slider also applies to broken leaders", () => {
    expect(pick("broken")).toEqual([brokenLeader]);
    expect(pick("broken", sliderToRs(80))).toEqual([brokenLeader, brokenMid]);
  });

  it("all names shows everything, including names with no history", () => {
    expect(pick("all")).toEqual(rows);
  });

  it("leaders are filtered out rather than just ranked lower", () => {
    expect(pick("leaders")).not.toContain(laggard);
    expect(pick("leaders")).not.toContain(noHistory);
  });

  it("Recent breakouts ignores the slider but needs RS >= P50 and an unbroken trend", () => {
    expect(BREAKOUT_MIN_RS).toBe(0.5);
    expect(pick("breakouts")).toEqual([midBreakout]);
    expect(pick("breakouts", sliderToRs(99))).toEqual([midBreakout]);
    expect(pick("breakouts", sliderToRs(50))).toEqual([midBreakout]);
  });
});

describe("migrateLeadership", () => {
  it("maps the old Leaders and Broad leaders options onto Leaders plus a Min RS value", () => {
    expect(migrateLeadership("p90")).toEqual({ filter: "leaders", minRs: 90 });
    expect(migrateLeadership("p80")).toEqual({ filter: "leaders", minRs: 80 });
  });

  it("keeps current options and falls back to Leaders", () => {
    expect(migrateLeadership("broken")).toEqual({ filter: "broken", minRs: null });
    expect(migrateLeadership("breakouts")).toEqual({ filter: "breakouts", minRs: null });
    expect(migrateLeadership(null)).toEqual({ filter: "leaders", minRs: null });
    expect(migrateLeadership("nonsense")).toEqual({ filter: "leaders", minRs: null });
  });
});

describe("persisted filters", () => {
  const store = new Map<string, string>();
  const storage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
  } as Storage;

  it("saves the leadership option and Min RS like the other filters", () => {
    expect(readPersisted<number | null>("minRs", null, storage)).toBeNull();
    writePersisted<LeadershipFilter>("leadership", "breakouts", storage);
    writePersisted<number | null>("minRs", 85, storage);
    expect(readPersisted<LeadershipFilter>("leadership", "leaders", storage)).toBe("breakouts");
    expect(readPersisted<number | null>("minRs", null, storage)).toBe(85);
  });
});

describe("breakoutLabel", () => {
  it("names the breakout week and base length", () => {
    expect(breakoutLabel(breakoutInfo)).toBe("Breakout 2026-09-14 · 6-week base");
  });
});

describe("fmtRs", () => {
  it("formats the percentile", () => {
    expect(fmtRs(0.974)).toBe("P97");
    expect(fmtRs(1)).toBe("P100");
    expect(fmtRs(null)).toBe("—");
  });
});

describe("noSetupLabel", () => {
  it("labels a leader with no setup, and any other name as having no active setup", () => {
    expect(noSetupLabel(leader)).toBe(NO_SETUP_LEADER);
    expect(noSetupLabel(leader)).toBe("No setup / leader");
    expect(noSetupLabel(laggard)).toBe("no active setup");
    expect(noSetupLabel(brokenLeader)).toBe("no active setup");
    expect(noSetupLabel(midLeader)).toBe("no active setup");
    expect(noSetupLabel(midLeader, 0.8)).toBe(NO_SETUP_LEADER);
  });
});

describe("triggerHint", () => {
  const base = { trigger: null, trigger_distance_pct: null, nearest_trigger: null, nearest_trigger_distance_pct: null, nearest_trigger_label: null };

  it("uses the weekly setup's trigger when there is one", () => {
    expect(triggerHint({ ...base, trigger: 106, trigger_distance_pct: 1.9, nearest_trigger: 110 })).toEqual({
      price: 106,
      distancePct: 1.9,
      label: "setup trigger",
      nearest: false,
    });
  });

  it("falls back to the nearest weekly high for a name with no setup", () => {
    expect(
      triggerHint({ ...base, nearest_trigger: 101.5, nearest_trigger_distance_pct: 0.8, nearest_trigger_label: "last week's high" }),
    ).toEqual({ price: 101.5, distancePct: 0.8, label: "last week's high", nearest: true });
  });

  it("has nothing to show for a name at its highs with no setup", () => {
    expect(triggerHint(base)).toBeNull();
  });
});

describe("formatWeight", () => {
  it("shows whole weights without decimals and keeps one decimal otherwise", () => {
    expect(formatWeight(32)).toBe("32%");
    expect(formatWeight(15.0)).toBe("15%");
    expect(formatWeight(35.555)).toBe("35.6%");
  });
});
