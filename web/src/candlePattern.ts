import type { ScanRow } from "./api";

/** Stock Scanner "Candle Pattern" filter: inside bar or hammer on the last completed weekly or daily bar. */
export type CandlePattern = "any" | "weekly_hammer" | "weekly_inside" | "daily_hammer" | "daily_inside";

export const CANDLE_PATTERNS: readonly CandlePattern[] = ["any", "weekly_hammer", "weekly_inside", "daily_hammer", "daily_inside"];

export const CANDLE_PATTERN_LABELS: Record<CandlePattern, string> = {
  any: "Any",
  weekly_hammer: "Weekly Hammer",
  weekly_inside: "Weekly Inside",
  daily_hammer: "Daily Hammer",
  daily_inside: "Daily Inside",
};

type PatternFields = { candle_patterns?: ScanRow["candle_patterns"] | null };

/** Whether a scan row's last completed weekly / daily bar shows the chosen pattern. Rows without the field never match a pattern. */
export function matchesCandlePattern(r: PatternFields, pattern: CandlePattern): boolean {
  if (pattern === "any") return true;
  const p = r.candle_patterns;
  if (!p) return false;
  switch (pattern) {
    case "weekly_hammer":
      return !!p.W?.hammer;
    case "weekly_inside":
      return !!p.W?.inside;
    case "daily_hammer":
      return !!p.D?.hammer;
    case "daily_inside":
      return !!p.D?.inside;
  }
}

export function isCandlePattern(v: unknown): v is CandlePattern {
  return typeof v === "string" && (CANDLE_PATTERNS as readonly string[]).includes(v);
}

/** The old "Setup" filter's saved value, carried over: Inside week / Weekly hammer map across, the rest becomes Any. */
export function migrateSetupFilter(old: unknown): CandlePattern {
  if (old === "inside") return "weekly_inside";
  if (old === "hammer") return "weekly_hammer";
  return "any";
}
