import { describe, expect, it } from "vitest";
import type { ScanRow } from "./api";
import {
  BREAKOUT_MIN_RS,
  LEADER_RS,
  MIN_RS_RANGE,
  NO_SETUP_LEADER,
  breakoutLabel,
  dailyTrendBadge,
  failedBreakoutLabel,
  fmtRs,
  formatWeight,
  leadershipUsesMinRs,
  matchesLeadership,
  migrateLeadership,
  noSetupLabel,
  sliderToRs,
  triggerHint,
  type LeadershipFilter,
} from "./leadership";
import { sortBy } from "./components/ScanTable";
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

const row = (
  rs: number | null,
  breakdown: "none" | "warning" | "broken" = "none",
  breakout: Breakout | null = null,
  has_setup = false,
  triggered: boolean | null = false,
) => ({
  rs,
  leadership: { breakdown },
  breakout,
  has_setup,
  triggered,
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

  it("Broken leaders ignores the Min RS slider and lists every broken trend", () => {
    expect(pick("broken")).toEqual([brokenLeader, brokenMid, brokenBreakout]);
    expect(pick("broken", sliderToRs(99))).toEqual([brokenLeader, brokenMid, brokenBreakout]);
  });

  it("only Leaders and Weekly setups use the Min RS slider", () => {
    expect(leadershipUsesMinRs("leaders")).toBe(true);
    expect(leadershipUsesMinRs("setups_pending")).toBe(true);
    expect(leadershipUsesMinRs("setups_triggered")).toBe(true);
    expect(leadershipUsesMinRs("breakouts")).toBe(false);
    expect(leadershipUsesMinRs("broken")).toBe(false);
    expect(leadershipUsesMinRs("daily_bullish")).toBe(false);
    expect(leadershipUsesMinRs("daily_bearish")).toBe(false);
    expect(leadershipUsesMinRs("all")).toBe(false);
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

describe("Weekly setups", () => {
  const pendingLeader = row(0.96, "none", null, true, false);
  const pendingWarning = row(0.92, "warning", null, true, false);
  const pendingMid = row(0.84, "none", null, true, false);
  const triggeredLeader = row(0.95, "none", null, true, true);
  const triggeredMid = row(0.83, "none", null, true, true);
  const setupBroken = row(0.97, "broken", null, true, false);
  const setupLaggard = row(0.3, "none", null, true, true);
  const setupNoRs = row(null, "none", null, true, false);
  const all = [
    pendingLeader,
    pendingWarning,
    pendingMid,
    triggeredLeader,
    triggeredMid,
    setupBroken,
    setupLaggard,
    setupNoRs,
    leader,
    midLeader,
  ];
  const pending = (minRs?: number) => all.filter((r) => matchesLeadership(r, "setups_pending", minRs));
  const triggered = (minRs?: number) => all.filter((r) => matchesLeadership(r, "setups_triggered", minRs));

  it("awaiting trigger lists leaders with a pending weekly setup", () => {
    expect(pending()).toEqual([pendingLeader, pendingWarning]);
    expect(pending()).not.toContain(triggeredLeader);
  });

  it("triggered lists leaders whose weekly setup has already fired", () => {
    expect(triggered()).toEqual([triggeredLeader]);
    expect(triggered()).not.toContain(pendingLeader);
  });

  it("drops leaders that have no weekly setup", () => {
    expect(pending()).not.toContain(leader);
    expect(triggered(sliderToRs(50))).not.toContain(leader);
  });

  it("reuses the Min RS slider for both setup views", () => {
    expect(pending(sliderToRs(80))).toEqual([pendingLeader, pendingWarning, pendingMid]);
    expect(triggered(sliderToRs(80))).toEqual([triggeredLeader, triggeredMid]);
    expect(pending(sliderToRs(95))).toEqual([pendingLeader]);
    expect(triggered(sliderToRs(50))).not.toContain(setupNoRs);
  });

  it("each setup view is a subset of Leaders at the same slider position", () => {
    for (const v of [50, 80, 90, 99]) {
      const leaders = all.filter((r) => matchesLeadership(r, "leaders", sliderToRs(v)));
      for (const r of [...pending(sliderToRs(v)), ...triggered(sliderToRs(v))]) expect(leaders).toContain(r);
    }
  });

  it("treats a row with no has_setup field as having no setup", () => {
    expect(matchesLeadership({ rs: 0.99, leadership: { breakdown: "none" } }, "setups_pending")).toBe(false);
    expect(matchesLeadership({ rs: 0.99, leadership: { breakdown: "none" }, has_setup: true }, "setups_triggered")).toBe(false);
  });
});

type Failed = NonNullable<ScanRow["failed_breakout"]>;
const failedInfo = (failed_on: string, below_pct: number): Failed => ({
  week: "2026-09-14",
  weeks_ago: 4,
  base_weeks: 6,
  level: 100,
  volume_x: 2.4,
  breakout_close: 106,
  failed_on,
  sessions_below: 3,
  close: 100 + below_pct,
  below_pct,
  low_pct: below_pct - 1,
});

describe("Failed breakouts", () => {
  const withFailed = (rs: number | null, breakdown: "none" | "warning" | "broken", failed: Failed | null, breakout: Breakout | null = null) => ({
    ...row(rs, breakdown, breakout),
    failed_breakout: failed,
  });
  const failedMid = withFailed(0.62, "none", failedInfo("2026-10-14", -3));
  const failedLeader = withFailed(0.95, "warning", failedInfo("2026-10-08", -6));
  const failedBroken = withFailed(0.7, "broken", failedInfo("2026-10-02", -12));
  const failedWeak = withFailed(0.3, "none", failedInfo("2026-10-10", -5));
  const failedNoRs = withFailed(null, "none", failedInfo("2026-10-10", -5));
  const held = withFailed(0.9, "none", null);
  const all = [failedMid, failedLeader, failedBroken, failedWeak, failedNoRs, held, withFailed(0.97, "none", null)];
  const failed = (minRs?: number) => all.filter((r) => matchesLeadership(r, "failed_breakouts", minRs));

  it("lists names whose breakout level was lost, with RS >= P50 and any trend", () => {
    expect(failed()).toEqual([failedMid, failedLeader, failedBroken]);
  });

  it("ignores the Min RS slider", () => {
    expect(failed(sliderToRs(99))).toEqual(failed(sliderToRs(50)));
    expect(leadershipUsesMinRs("failed_breakouts")).toBe(false);
  });

  it("a row without a failed breakout, or with no field at all, never matches", () => {
    expect(failed()).not.toContain(held);
    expect(matchesLeadership({ rs: 0.99, leadership: { breakdown: "none" } }, "failed_breakouts")).toBe(false);
  });

  it("a failed breakout is no longer a Recent breakout", () => {
    const live = withFailed(0.8, "none", null, breakoutInfo);
    const lost = withFailed(0.8, "none", failedInfo("2026-10-14", -2), breakoutInfo);
    expect(matchesLeadership(live, "breakouts")).toBe(true);
    expect(matchesLeadership(lost, "breakouts")).toBe(false);
    expect(matchesLeadership(lost, "failed_breakouts")).toBe(true);
  });

  it("sorts by the most recent failure or by how far below the level", () => {
    const byDate = sortBy(failed(), (r) => r.failed_breakout?.failed_on, -1);
    expect(byDate).toEqual([failedMid, failedLeader, failedBroken]);
    const bySeverity = sortBy(failed(), (r) => r.failed_breakout?.below_pct, 1);
    expect(bySeverity).toEqual([failedBroken, failedLeader, failedMid]);
  });

  it("labels the badge with the breakout date and distance below the level", () => {
    expect(failedBreakoutLabel(failedInfo("2026-10-14", -6.24))).toBe("Failed breakout 2026-09-14 · 6.2% below");
  });

  it("is kept by the saved-filter migration", () => {
    expect(migrateLeadership("failed_breakouts")).toEqual({ filter: "failed_breakouts", minRs: null });
  });
});

describe("daily MACD trend change", () => {
  const bull = { ...row(0.2), daily_trend: "bullish" as const };
  const bear = { ...row(0.99, "broken"), daily_trend: "bearish" as const };
  const earlier = { ...row(0.95), daily_trend: null };

  it("keeps a name only when the latest daily bar is that trigger", () => {
    expect(matchesLeadership(bull, "daily_bullish")).toBe(true);
    expect(matchesLeadership(bear, "daily_bullish")).toBe(false);
    expect(matchesLeadership(earlier, "daily_bullish")).toBe(false);
    expect(matchesLeadership(row(0.99), "daily_bullish")).toBe(false);
    expect(matchesLeadership(bear, "daily_bearish")).toBe(true);
    expect(matchesLeadership(bull, "daily_bearish")).toBe(false);
  });

  it("ignores the Min RS slider, a broken trend and whether there is a weekly setup", () => {
    expect(matchesLeadership(bull, "daily_bullish", sliderToRs(99))).toBe(true);
    expect(matchesLeadership(bear, "daily_bearish", sliderToRs(50))).toBe(true);
    expect(leadershipUsesMinRs("daily_bullish")).toBe(false);
    expect(leadershipUsesMinRs("daily_bearish")).toBe(false);
  });

  it("labels the row chip the way the other setup badges are labeled", () => {
    expect(dailyTrendBadge("bullish")).toMatchObject({ label: "Daily bullish", tone: "bull" });
    expect(dailyTrendBadge("bearish")).toMatchObject({ label: "Daily bearish", tone: "bear" });
    expect(dailyTrendBadge(null)).toBeNull();
    expect(dailyTrendBadge(undefined)).toBeNull();
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
    expect(migrateLeadership("setups")).toEqual({ filter: "setups_pending", minRs: null });
    expect(migrateLeadership("setups_pending")).toEqual({ filter: "setups_pending", minRs: null });
    expect(migrateLeadership("setups_triggered")).toEqual({ filter: "setups_triggered", minRs: null });
    expect(migrateLeadership("daily_bullish")).toEqual({ filter: "daily_bullish", minRs: null });
    expect(migrateLeadership("daily_bearish")).toEqual({ filter: "daily_bearish", minRs: null });
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
