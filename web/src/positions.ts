export interface PositionStats {
  /** Percent gain (positive) or loss (negative) from the entry price to the last price. */
  pct: number;
  /** Dollar P/L, or null when no share count was entered. */
  pnl: number | null;
  /** Calendar days since the entry date (0 on the entry day). */
  days: number;
}

const DAY_MS = 86_400_000;

function isoToUtc(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Today's date in the browser's time zone as YYYY-MM-DD. */
export function todayIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function daysBetween(fromIso: string, toIso: string): number {
  return Math.round((isoToUtc(toIso) - isoToUtc(fromIso)) / DAY_MS);
}

export function positionStats(
  pos: { entry_price: number; shares: number | null; entry_date: string },
  last: number,
  today: string,
): PositionStats {
  return {
    pct: ((last - pos.entry_price) / pos.entry_price) * 100,
    pnl: pos.shares ? (last - pos.entry_price) * pos.shares : null,
    days: Math.max(0, daysBetween(pos.entry_date, today)),
  };
}

export function fmtPnl(v: number): string {
  const abs = Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}$${abs}`;
}

export interface EntryForm {
  price: string;
  shares: string;
  date: string;
}

export type ParsedEntry =
  | { ok: true; entry_price: number | null; shares: number | null; entry_date: string }
  | { ok: false; error: string };

/** Validate the entry form. A blank price is allowed only when `priceOptional` (the server then uses the last price). */
export function parseEntry(form: EntryForm, today: string, priceOptional = false): ParsedEntry {
  const priceText = form.price.trim().replace(/^\$/, "").replace(/,/g, "");
  const sharesText = form.shares.trim().replace(/,/g, "");
  let entry_price: number | null = null;
  if (priceText) {
    entry_price = Number(priceText);
    if (!Number.isFinite(entry_price) || entry_price <= 0) return { ok: false, error: "Entry price must be a positive number" };
  } else if (!priceOptional) {
    return { ok: false, error: "Enter an entry price" };
  }
  let shares: number | null = null;
  if (sharesText) {
    shares = Number(sharesText);
    if (!Number.isFinite(shares) || shares <= 0) return { ok: false, error: "Shares must be a positive number (or blank)" };
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.date)) return { ok: false, error: "Enter an entry date" };
  if (form.date > today) return { ok: false, error: "Entry date can't be in the future" };
  return { ok: true, entry_price, shares, entry_date: form.date };
}
