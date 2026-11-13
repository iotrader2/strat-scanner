/** Rows-per-page choices. 0 means every row on one page. */
export const PAGE_SIZES = [25, 50, 100, 250, 0] as const;
export const DEFAULT_PAGE_SIZE = 50;

export function normalizePageSize(raw: unknown): number {
  return typeof raw === "number" && (PAGE_SIZES as readonly number[]).includes(raw) ? raw : DEFAULT_PAGE_SIZE;
}

export interface PageSlice<T> {
  rows: T[];
  /** Zero-based page actually shown (clamped to the last page). */
  page: number;
  pages: number;
  /** One-based first and last row shown; both 0 when there are no rows. */
  from: number;
  to: number;
  total: number;
}

/** The rows on ``page`` (zero-based). A page past the end shows the last page; size 0 shows everything. */
export function paginate<T>(items: T[], page: number, size: number): PageSlice<T> {
  const total = items.length;
  if (size <= 0 || total <= size) {
    return { rows: items, page: 0, pages: 1, from: total ? 1 : 0, to: total, total };
  }
  const pages = Math.ceil(total / size);
  const p = Math.min(Math.max(0, Math.floor(page) || 0), pages - 1);
  const start = p * size;
  const rows = items.slice(start, start + size);
  return { rows, page: p, pages, from: start + 1, to: start + rows.length, total };
}
