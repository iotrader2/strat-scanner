import { describe, expect, it } from "vitest";
import {
  BROAD_RS,
  LEADER_RS,
  NO_SETUP_LEADER,
  fmtRs,
  formatWeight,
  matchesLeadership,
  noSetupLabel,
  triggerHint,
  type LeadershipFilter,
} from "./leadership";
import { readPersisted, writePersisted } from "./persist";

const row = (rs: number | null, breakdown: "none" | "warning" | "broken" = "none") => ({ rs, leadership: { breakdown } });

const leader = row(0.97);
const weakening = row(0.93, "warning");
const broadOnly = row(0.85);
const brokenLeader = row(0.96, "broken");
const brokenBroad = row(0.82, "broken");
const laggard = row(0.4);
const noHistory = row(null);
const rows = [leader, weakening, broadOnly, brokenLeader, brokenBroad, laggard, noHistory];
const pick = (f: LeadershipFilter) => rows.filter((r) => matchesLeadership(r, f));

describe("matchesLeadership", () => {
  it("defaults to the top decile and never lists a broken trend as a leader", () => {
    expect(LEADER_RS).toBe(0.9);
    expect(pick("p90")).toEqual([leader, weakening]);
  });

  it("the broad cut adds the P80-P90 names but still drops broken trends", () => {
    expect(BROAD_RS).toBe(0.8);
    expect(pick("p80")).toEqual([leader, weakening, broadOnly]);
  });

  it("shows the demoted leaders on their own", () => {
    expect(pick("broken")).toEqual([brokenLeader, brokenBroad]);
  });

  it("all names shows everything, including names with no history", () => {
    expect(pick("all")).toEqual(rows);
  });

  it("leaders are filtered out rather than just ranked lower", () => {
    expect(pick("p90")).not.toContain(laggard);
    expect(pick("p90")).not.toContain(noHistory);
  });

  it("is saved like the other filters, with leaders-only as the default", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    } as Storage;
    expect(readPersisted<LeadershipFilter>("leadership", "p90", storage)).toBe("p90");
    writePersisted<LeadershipFilter>("leadership", "all", storage);
    expect(readPersisted<LeadershipFilter>("leadership", "p90", storage)).toBe("all");
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
