import type { ScanRow, ThemeInfo } from "./api";

/** Scanner theme filter values: "" = all themes, NO_THEME = stocks and ETFs outside every theme, else a theme id. */
export const NO_THEME = "none";

type ThemeFields = Pick<ScanRow, "theme" | "secondary_themes">;

/** Whether a row passes the theme filter: a stock matches the theme it belongs to as primary or secondary member. */
export function matchesTheme(r: ThemeFields, filter: string): boolean {
  if (!filter) return true;
  if (filter === NO_THEME) return !r.theme && !(r.secondary_themes?.length ?? 0);
  return r.theme === filter || (r.secondary_themes ?? []).includes(filter);
}

/** Dropdown options for the filter: all, no theme, then every theme by name. */
export function themeOptions(themes: ThemeInfo[]): { value: string; label: string }[] {
  return [
    { value: "", label: "All themes" },
    ...[...themes].sort((a, b) => a.name.localeCompare(b.name)).map((t) => ({ value: t.id, label: t.name })),
    { value: NO_THEME, label: "No theme (ETFs, others)" },
  ];
}

/** Display name for a theme id (falls back to the id while the config loads). */
export function themeName(themes: ThemeInfo[], id: string): string {
  if (id === NO_THEME) return "No theme";
  return themes.find((t) => t.id === id)?.name ?? id;
}

/** Scanner link that filters to a theme. */
export function scanThemeHref(id: string): string {
  return `/?theme=${encodeURIComponent(id)}`;
}
