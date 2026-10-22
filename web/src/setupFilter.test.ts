import { describe, expect, it } from "vitest";
import { matchesSetup, triggerChip, type SetupFilter } from "./setupFilter";
import { readPersisted, writePersisted } from "./persist";

const W = (inside = false, hammer = false) => ({ inside, hammer }) as never;
const row = (trigger: number | null, triggered: boolean | null, w = W()) => ({ trigger, triggered, tf: { W: w } });

const triggered212 = row(105, true); // e.g. Weekly 2-1-2 bullish (triggered)
const pendingInside = row(110, false, W(true));
const pendingHammer = row(98, false, W(false, true));
const noSetup = row(null, null, null as never);
const rows = [triggered212, pendingInside, pendingHammer, noSetup];

const pick = (f: SetupFilter) => rows.filter((r) => matchesSetup(r, f));

describe("matchesSetup", () => {
  it("Already triggered keeps only rows whose weekly setup has the triggered label", () => {
    expect(pick("triggered")).toEqual([triggered212]);
  });

  it("keeps the existing options working", () => {
    expect(pick("any")).toEqual(rows);
    expect(pick("pending")).toEqual([pendingInside, pendingHammer]);
    expect(pick("inside")).toEqual([pendingInside]);
    expect(pick("hammer")).toEqual([pendingHammer]);
  });

  it("Already triggered and Awaiting trigger never overlap", () => {
    for (const r of rows) expect(matchesSetup(r, "triggered") && matchesSetup(r, "pending")).toBe(false);
  });

  it("is saved like the other filters", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    } as Storage;
    writePersisted<SetupFilter>("setup", "triggered", storage);
    expect(readPersisted<SetupFilter>("setup", "any", storage)).toBe("triggered");
  });
});

describe("triggerChip", () => {
  it("is null while the setup is awaiting its trigger", () => {
    expect(triggerChip({ triggered: false, live: false, trigger: 310.53 })).toBeNull();
    expect(triggerChip({ triggered: null })).toBeNull();
  });

  it("says when the week in progress broke the trigger", () => {
    expect(triggerChip({ triggered: true, live: true, trigger: 310.53 })).toEqual({
      label: "triggered this week",
      title: "This week's high traded above the trigger 310.53 (set by last completed week)",
    });
    expect(triggerChip({ triggered: true, live: false, trigger: 9 })?.label).toBe("triggered");
    expect(triggerChip({ triggered: true })?.label).toBe("triggered");
  });

  it("puts a live break in the already-triggered Setup filter", () => {
    const row = { trigger: 310.53, triggered: true, tf: { W: null } };
    expect(matchesSetup(row as never, "triggered")).toBe(true);
    expect(matchesSetup(row as never, "pending")).toBe(false);
  });
});
