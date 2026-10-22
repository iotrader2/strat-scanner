import { describe, expect, it } from "vitest";
import { filterThemes, RANK_N, sortThemes, sortThemesWeakest, themeTiles } from "./themeCards";
import type { ThemeCard } from "./api";

const card = (id: string, name: string, score: number, perf: Partial<Record<"1m" | "3m" | "6m", number | null>>, members: string[], also: string[] = []) =>
  ({
    id,
    name,
    description: "",
    count: members.length,
    members: members.map((symbol) => ({ symbol, name: `${symbol} Corp`, also: false })),
    also: also.map((symbol) => ({ symbol, name: `${symbol} Corp`, also: true })),
    row: { score, perf: { "1m": null, "3m": null, "6m": null, ...perf } },
    candles: [],
  }) as unknown as ThemeCard;

const THEMES = [
  card("memory", "Memory & storage", 70, { "1m": 12, "3m": 40, "6m": 90 }, ["MU", "WDC"]),
  card("banks", "Regional banks", 55, { "1m": -3, "3m": 8, "6m": null }, ["KEY", "RF"], ["SOFI"]),
  card("cyber", "Cybersecurity", 70, { "1m": 5, "3m": -2, "6m": 11 }, ["CRWD", "PANW"]),
];

describe("sortThemes", () => {
  it("ranks by score with ties by name", () => {
    expect(sortThemes(THEMES, "score").map((t) => t.id)).toEqual(["cyber", "memory", "banks"]);
  });

  it("ranks by index return for a period, unknown returns last", () => {
    expect(sortThemes(THEMES, "perf_1m").map((t) => t.id)).toEqual(["memory", "cyber", "banks"]);
    expect(sortThemes(THEMES, "perf_3m").map((t) => t.id)).toEqual(["memory", "banks", "cyber"]);
    expect(sortThemes(THEMES, "perf_6m").map((t) => t.id)).toEqual(["memory", "cyber", "banks"]);
  });

  it("does not mutate its input", () => {
    const before = THEMES.map((t) => t.id);
    sortThemes(THEMES, "perf_1m");
    expect(THEMES.map((t) => t.id)).toEqual(before);
  });
});

describe("filterThemes", () => {
  it("keeps everything for a blank query", () => {
    expect(filterThemes(THEMES, "  ")).toHaveLength(3);
  });

  it("matches theme names and ids case-insensitively", () => {
    expect(filterThemes(THEMES, "BANK").map((t) => t.id)).toEqual(["banks"]);
    expect(filterThemes(THEMES, "cyber").map((t) => t.id)).toEqual(["cyber"]);
  });

  it("matches a member ticker exactly, primary or secondary, and member names loosely", () => {
    expect(filterThemes(THEMES, "mu").map((t) => t.id)).toEqual(["memory"]);
    expect(filterThemes(THEMES, "sofi").map((t) => t.id)).toEqual(["banks"]);
    expect(filterThemes(THEMES, "crw").map((t) => t.id)).toEqual(["cyber"]);
    expect(filterThemes(THEMES, "zzz")).toEqual([]);
  });
});

describe("themeTiles (Top / Bottom 12)", () => {
  const MANY = Array.from({ length: 82 }, (_, i) =>
    card(`t${i}`, `Theme ${String(i).padStart(2, "0")}`, i, { "1m": i % 5 === 0 ? null : 100 - i, "3m": i, "6m": i }, [`M${i}`]),
  );
  const base = { query: "", expanded: false, shown: 24 };

  it("shows exactly 12 tiles for Top 12 and Bottom 12, for every sort", () => {
    expect(RANK_N).toBe(12);
    for (const sort of ["score", "perf_1m", "perf_3m", "perf_6m"] as const) {
      for (const dir of ["top", "bottom"] as const) {
        const grid = themeTiles(MANY, { ...base, sort, dir });
        expect(grid.tiles).toHaveLength(12);
        expect(grid.more).toBe(0);
        expect(new Set(grid.tiles.map((t) => t.id)).size).toBe(12);
      }
    }
  });

  it("takes the strongest / weakest by the current sort", () => {
    expect(themeTiles(MANY, { ...base, sort: "score", dir: "top" }).tiles.map((t) => t.row.score)).toEqual(
      Array.from({ length: 12 }, (_, i) => 81 - i),
    );
    expect(themeTiles(MANY, { ...base, sort: "score", dir: "bottom" }).tiles.map((t) => t.row.score)).toEqual(
      Array.from({ length: 12 }, (_, i) => i),
    );
    // 1M: higher index = lower return; unknown (every 5th) returns never count as the weakest.
    const weak = themeTiles(MANY, { ...base, sort: "perf_1m", dir: "bottom" }).tiles;
    expect(weak[0].id).toBe("t81");
    expect(weak.every((t) => t.row.perf?.["1m"] !== null)).toBe(true);
    expect(themeTiles(MANY, { ...base, sort: "perf_1m", dir: "top" }).tiles[0].id).toBe("t1");
  });

  it("lists everything, paged, when expanded or searching", () => {
    const all = themeTiles(MANY, { ...base, sort: "score", dir: "top", expanded: true, shown: 82 });
    expect(all.tiles).toHaveLength(82);
    const paged = themeTiles(MANY, { ...base, sort: "score", dir: "top", expanded: true });
    expect(paged.tiles).toHaveLength(24);
    expect(paged.more).toBe(58);
    const search = themeTiles(MANY, { ...base, sort: "score", dir: "top", query: "theme 1" });
    expect(search.tiles.map((t) => t.id).sort()).toEqual(["t10", "t11", "t12", "t13", "t14", "t15", "t16", "t17", "t18", "t19"]);
    expect(search.matches).toBe(10);
    expect(search.more).toBe(0);
  });

  it("sortThemesWeakest keeps unknown returns last", () => {
    expect(sortThemesWeakest(THEMES, "perf_6m").map((t) => t.id)).toEqual(["cyber", "memory", "banks"]);
    expect(sortThemesWeakest(THEMES, "score").map((t) => t.id)).toEqual(["banks", "memory", "cyber"]);
  });
});
