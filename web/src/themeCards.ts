import type { PerfPeriod, ThemeCard } from "./api";

export type ThemeSort = "score" | "perf_1m" | "perf_3m" | "perf_6m";

export const THEME_SORTS: { key: ThemeSort; label: string }[] = [
  { key: "score", label: "Score" },
  { key: "perf_1m", label: "1M" },
  { key: "perf_3m", label: "3M" },
  { key: "perf_6m", label: "6M" },
];

/** Strongest first: by score, or by equal-weight index return over a period (unknown returns last); ties by name. */
export function sortThemes(themes: ThemeCard[], key: ThemeSort): ThemeCard[] {
  const value = (t: ThemeCard): number | null =>
    key === "score" ? t.row.score : (t.row.perf?.[key.slice(5) as PerfPeriod] ?? null);
  return [...themes].sort((a, b) => {
    const av = value(a);
    const bv = value(b);
    if (av === null && bv === null) return a.name.localeCompare(b.name);
    if (av === null) return 1;
    if (bv === null) return -1;
    return bv - av || a.name.localeCompare(b.name);
  });
}

/** Themes whose name, id, description or member tickers contain the query (case-insensitive; blank keeps everything). */
export function filterThemes(themes: ThemeCard[], query: string): ThemeCard[] {
  const q = query.trim().toLowerCase();
  if (!q) return themes;
  return themes.filter(
    (t) =>
      t.name.toLowerCase().includes(q) ||
      t.id.includes(q) ||
      t.members.some((m) => m.symbol.toLowerCase() === q || m.name.toLowerCase().includes(q)) ||
      t.also.some((m) => m.symbol.toLowerCase() === q),
  );
}

export type RankDir = "top" | "bottom";

/** How many theme tiles "Top 12" / "Bottom 12" show. */
export const RANK_N = 12;

/** Weakest first by the same key (unknown returns still last); ties keep sortThemes' name order. */
export function sortThemesWeakest(themes: ThemeCard[], key: ThemeSort): ThemeCard[] {
  const sorted = sortThemes(themes, key);
  const known = (t: ThemeCard) => (key === "score" ? true : (t.row.perf?.[key.slice(5) as PerfPeriod] ?? null) !== null);
  return [...sorted.filter(known).reverse(), ...sorted.filter((t) => !known(t))];
}

/**
 * The theme tiles the grid renders. "Top 12" / "Bottom 12" show exactly RANK_N tiles: the strongest or weakest by the
 * current sort. `expanded` (the "show all" chip, or jumping to a theme) and a search query list every match instead,
 * `shown` at a time, with `more` saying how many are left for "Show more".
 */
export function themeTiles(
  themes: ThemeCard[],
  opts: { sort: ThemeSort; dir: RankDir; query: string; expanded: boolean; shown: number; n?: number },
): { tiles: ThemeCard[]; matches: number; more: number } {
  const matches = filterThemes(themes, opts.query);
  const ordered = opts.dir === "bottom" ? sortThemesWeakest(matches, opts.sort) : sortThemes(matches, opts.sort);
  if (!opts.expanded && !opts.query.trim()) {
    return { tiles: ordered.slice(0, opts.n ?? RANK_N), matches: ordered.length, more: 0 };
  }
  const tiles = ordered.slice(0, opts.shown);
  return { tiles, matches: ordered.length, more: ordered.length - tiles.length };
}
