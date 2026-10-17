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
