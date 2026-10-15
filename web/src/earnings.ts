import type { Earnings } from "./api";

const TIMING: Record<string, string> = { BMO: "BMO (before open)", AMC: "AMC (after close)" };

function fmtDay(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function fmtWhen(days: number): string {
  return days === 0 ? "today" : days === 1 ? "tomorrow" : `in ${days} days`;
}

/** Tooltip lines for the earnings caution icon: date (or Yahoo's estimated range), timing, countdown. */
export function earningsLines(e: Earnings): string[] {
  const date = e.date_end ? `${fmtDay(e.date)} – ${fmtDay(e.date_end)} (estimated range)` : fmtDay(e.date);
  const timing = e.timing ? TIMING[e.timing] ?? e.timing : "time TBD";
  return [`Earnings ${date}`, `${timing} · ${fmtWhen(e.days_until)}`];
}
