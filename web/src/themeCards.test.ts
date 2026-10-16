import { describe, expect, it } from "vitest";
import { filterThemes, sortThemes } from "./themeCards";
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
