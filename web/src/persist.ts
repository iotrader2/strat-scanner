import { useEffect, useState } from "react";

const PREFIX = "strat:";

export function readPersisted<T>(key: string, fallback: T, storage: Storage = localStorage): T {
  try {
    const raw = storage.getItem(PREFIX + key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writePersisted<T>(key: string, value: T, storage: Storage = localStorage): void {
  storage.setItem(PREFIX + key, JSON.stringify(value));
}

/** useState backed by localStorage, so the value survives navigation and full page reloads. */
export function usePersisted<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => readPersisted(key, initial));
  useEffect(() => writePersisted(key, value), [key, value]);
  return [value, setValue] as const;
}

export const LAST_TAB_KEY = "lastTab";
const TABS = ["/", "/sectors", "/watchlist"];

/** Top-level tab (Sectors, Stock Scanner or Watchlist) for a location, including its query string, or null for other pages. */
export function tabLocation(pathname: string, search: string): string | null {
  return TABS.includes(pathname) ? pathname + search : null;
}

/** Tab for first-time visitors: Sectors first, then drill into the Stock Scanner. */
export const DEFAULT_TAB = "/sectors";

/**
 * Where to send a visit to the bare app URL: the last tab the user had open, or Sectors when nothing
 * valid is saved. Deep links (any path or query string) are always respected. Null means stay put.
 */
export function restoreTarget(pathname: string, search: string, lastTab: string | null): string | null {
  if (pathname !== "/" || search !== "") return null;
  const saved = lastTab && TABS.includes(lastTab.split("?")[0]) ? lastTab : DEFAULT_TAB;
  return saved === "/" ? null : saved;
}

const TITLES: Record<string, string> = { "/": "Stock Scanner", "/sectors": "Sectors", "/watchlist": "Watchlist" };

/** Browser tab title for a route. */
export function pageTitle(pathname: string): string {
  const stock = pathname.match(/^\/stock\/([^/]+)/);
  const name = stock ? decodeURIComponent(stock[1]).toUpperCase() : TITLES[pathname];
  return name ? `${name} · Strat Scanner` : "Strat Scanner";
}

export const TIMEFRAMES = ["M", "W", "D"] as const;
export function isTimeframe(v: unknown): v is (typeof TIMEFRAMES)[number] {
  return typeof v === "string" && (TIMEFRAMES as readonly string[]).includes(v);
}
