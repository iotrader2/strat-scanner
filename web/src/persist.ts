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

/** Saved keys of Stock Scanner filters that were removed. Nothing reads them; they are cleared on load. */
export const RETIRED_FILTER_KEYS = ["continuityFilter", "continuity"] as const;

export function clearRetiredFilters(storage: Storage = localStorage): void {
  try {
    for (const key of RETIRED_FILTER_KEYS) storage.removeItem(PREFIX + key);
  } catch {
    // Storage unavailable (private mode, quota): nothing to clear.
  }
}

/** useState backed by localStorage, so the value survives navigation and full page reloads. */
export function usePersisted<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => readPersisted(key, initial));
  useEffect(() => writePersisted(key, value), [key, value]);
  return [value, setValue] as const;
}

export const LAST_TAB_KEY = "lastTab";
const TABS = ["/", "/market", "/themes", "/watchlist", "/positions", "/alerts"];

/** Saved locations from before Sectors became Themes. */
const LEGACY_TABS: Record<string, string> = { "/sectors": "/themes" };

/** Top-level tab (State of the Market, Themes, Stock Scanner, Watchlist or Positions) for a location, including its query string, or null for other pages. */
export function tabLocation(pathname: string, search: string): string | null {
  return TABS.includes(pathname) ? pathname + search : null;
}

/** Tab for first-time visitors: the market first, then Themes, then drill into the Stock Scanner. */
export const DEFAULT_TAB = "/market";

/**
 * Where to send a visit to the bare app URL: the last tab the user had open, or State of the Market when nothing
 * valid is saved. Deep links (any path or query string) are always respected. Null means stay put.
 */
export function restoreTarget(pathname: string, search: string, lastTab: string | null): string | null {
  if (pathname !== "/" || search !== "") return null;
  const remembered = lastTab ? (LEGACY_TABS[lastTab.split("?")[0]] ?? lastTab) : null;
  const saved = remembered && TABS.includes(remembered.split("?")[0]) ? remembered : DEFAULT_TAB;
  return saved === "/" ? null : saved;
}

const TITLES: Record<string, string> = { "/": "Stock Scanner", "/market": "State of the Market", "/themes": "Themes", "/watchlist": "Watchlist", "/positions": "Positions", "/alerts": "Alerts" };

/** Browser tab title for a route. */
export function pageTitle(pathname: string): string {
  const stock = pathname.match(/^\/stock\/([^/]+)/);
  const name = stock ? decodeURIComponent(stock[1]).toUpperCase() : TITLES[pathname];
  return name ? `${name} · TiltKiller` : "TiltKiller";
}

export const TIMEFRAMES = ["M", "W", "D"] as const;

/** Sticky chart timeframe of the detail page. */
export const DETAIL_TF_KEY = "detailTf";
export function isTimeframe(v: unknown): v is (typeof TIMEFRAMES)[number] {
  return typeof v === "string" && (TIMEFRAMES as readonly string[]).includes(v);
}

/**
 * Charts on the symbol page. ``5m`` is only this page: themes and the market stay on M / W / D,
 * so it is not part of {@link TIMEFRAMES}.
 */
export const DETAIL_CHARTS = ["5m", "D", "W", "M"] as const;
export type DetailChart = (typeof DETAIL_CHARTS)[number];

/** Segment buttons, left to right. */
export const DETAIL_CHART_BUTTONS: { id: DetailChart; label: string }[] = [
  { id: "5m", label: "5min" },
  { id: "D", label: "Daily" },
  { id: "W", label: "Weekly" },
  { id: "M", label: "Monthly" },
];

export function isDetailChart(v: unknown): v is DetailChart {
  return typeof v === "string" && (DETAIL_CHARTS as readonly string[]).includes(v);
}
