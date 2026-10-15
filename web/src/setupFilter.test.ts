import { describe, expect, it } from "vitest";
import { matchesSetup, type SetupFilter } from "./setupFilter";
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
