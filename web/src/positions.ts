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
  // Unrealized P/L stays on the original buy price. Pass remaining shares so a trim
  // shrinks the open dollar P/L without rewriting the cost the percent is measured from.
  return {
    pct: ((last - pos.entry_price) / pos.entry_price) * 100,
    pnl: pos.shares ? (last - pos.entry_price) * pos.shares : null,
    days: Math.max(0, daysBetween(pos.entry_date, today)),
  };
}

export interface TrimLot {
  shares: number;
  price: number;
}

/** Shares still held: initial size minus every trim. */
export function remainingShares(initialShares: number, trims: TrimLot[]): number {
  return initialShares - trims.reduce((sum, t) => sum + t.shares, 0);
}

/**
 * break_even = (initial_shares * initial_buy_price - sum(trim_shares * trim_price)) / remaining_shares
 * Trim proceeds reduce the cost left on the shares still held. Zero or negative is a free trade.
 */
export function breakEven(initialShares: number, buyPrice: number, trims: TrimLot[]): number {
  const remaining = remainingShares(initialShares, trims);
  const proceeds = trims.reduce((sum, t) => sum + t.shares * t.price, 0);
  return (initialShares * buyPrice - proceeds) / remaining;
}

/** Realized P/L from trims = sum(trim_shares * (trim_price - initial_buy_price)). */
export function realizedTrimPnl(buyPrice: number, trims: TrimLot[]): number {
  return trims.reduce((sum, t) => sum + t.shares * (t.price - buyPrice), 0);
}

export interface TrimPreview {
  remaining: number;
  /** Realized P/L of this trim alone, versus the original buy price. */
  realized: number;
  breakEven: number;
}

/** Live preview of one new trim on top of the lots already booked. */
export function trimPreview(
  pos: { entry_price: number; initial_shares: number; trims: TrimLot[] },
  next: TrimLot,
): TrimPreview {
  const trims = [...pos.trims, next];
  return {
    remaining: remainingShares(pos.initial_shares, trims),
    realized: next.shares * (next.price - pos.entry_price),
    breakEven: breakEven(pos.initial_shares, pos.entry_price, trims),
  };
}

export interface BreakEvenLabel {
  label: string;
  /** Short note when the basis is covered or a credit. */
  note: string | null;
}

/** "Free" at zero, a negative price with a note when trims paid more than the shares cost. */
export function formatBreakEven(value: number): BreakEvenLabel {
  if (!Number.isFinite(value)) return { label: "—", note: null };
  if (Math.abs(value) < 0.005) return { label: "Free", note: "Cost covered" };
  if (value < 0) {
    const abs = Math.abs(value).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return { label: `−${abs}`, note: "Free trade" };
  }
  return { label: value.toFixed(2), note: null };
}

export function fmtShares(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export function fmtTrimWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export interface TrimHistoryLine {
  id?: number;
  shares: number;
  price: number;
  trimmed_at: string;
}

/** Row tooltip: buy, remaining, break-even, realized P/L, and each trim. */
export function trimHistoryTitle(pos: {
  entry_price: number;
  shares: number | null;
  remaining_shares: number | null;
  break_even: number;
  realized_pnl: number;
  trims: TrimHistoryLine[];
}): string {
  const bought = pos.shares === null ? "—" : `${fmtShares(pos.shares)} sh`;
  const left = pos.remaining_shares === null ? "—" : `${fmtShares(pos.remaining_shares)} sh`;
  const lines = [
    `Buy ${bought} @ ${pos.entry_price.toFixed(2)}`,
    `Remaining ${left} · break-even ${formatBreakEven(pos.break_even).label}`,
    `Realized trim P/L ${fmtPnl(pos.realized_pnl)}`,
  ];
  for (const t of pos.trims) lines.push(`${fmtTrimWhen(t.trimmed_at)} — ${fmtShares(t.shares)} sh @ ${t.price.toFixed(2)}`);
  if (pos.trims.length === 0) lines.push("No trims");
  return lines.join("\n");
}

export interface TrimForm {
  price: string;
  shares: string;
}

export type ParsedTrim = { ok: true; price: number; shares: number } | { ok: false; error: string };

const CLOSE_INSTEAD = "That sells the whole position. Use Close position instead.";

/** Validate the trim dialog. Selling every share still held is refused. */
export function parseTrim(form: TrimForm, remaining: number | null): ParsedTrim {
  if (remaining === null || !(remaining > 0)) {
    return { ok: false, error: "Add a share count before trimming (use Edit entry)" };
  }
  const priceText = form.price.trim().replace(/^\$/, "").replace(/,/g, "");
  const sharesText = form.shares.trim().replace(/,/g, "");
  if (!priceText) return { ok: false, error: "Enter a trim price" };
  const price = Number(priceText);
  if (!Number.isFinite(price) || price <= 0) return { ok: false, error: "Trim price must be a positive number" };
  if (!sharesText) return { ok: false, error: "Enter the shares to trim" };
  const shares = Number(sharesText);
  if (!Number.isFinite(shares) || shares <= 0) return { ok: false, error: "Shares must be greater than 0" };
  if (shares >= remaining - 1e-9) return { ok: false, error: CLOSE_INSTEAD };
  return { ok: true, price, shares };
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
