/** The scanner's symbol search: ticker-only, uppercase, prefix match. */

export const SYMBOL_SEARCH_MAX = 12;

/** Uppercase and keep only ticker characters (A-Z, 0-9, "." and "-"), e.g. " brk.b " -> "BRK.B". */
export function sanitizeSymbol(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9.-]/g, "").slice(0, SYMBOL_SEARCH_MAX);
}

/**
 * The sanitized value plus where the caret goes: after the same characters it followed before
 * (anything stripped before the caret no longer counts), so typing in the middle does not jump to the end.
 */
export function sanitizeWithCaret(raw: string, caret: number | null): { value: string; caret: number } {
  const value = sanitizeSymbol(raw);
  const at = caret == null ? value.length : Math.min(sanitizeSymbol(raw.slice(0, caret)).length, value.length);
  return { value, caret: at };
}

/** Prefix match on the ticker only: "NV" finds NVDA and NVO, not names or themes. An empty query matches all. */
export function matchesSymbol(symbol: string, query: string): boolean {
  const q = sanitizeSymbol(query);
  return !q || symbol.toUpperCase().startsWith(q);
}

/** Moves the row whose symbol equals the query to the top, keeping the rest in their order. */
export function pinExactSymbol<T extends { symbol: string }>(rows: T[], query: string): T[] {
  const q = sanitizeSymbol(query);
  if (!q) return rows;
  const i = rows.findIndex((r) => r.symbol.toUpperCase() === q);
  return i <= 0 ? rows : [rows[i], ...rows.slice(0, i), ...rows.slice(i + 1)];
}
