import { PAGE_SIZES, type PageSlice } from "../pagination";

/** Rows-per-page picker, the visible range, and Prev / Next. */
export function Pager({
  slice,
  size,
  onPage,
  onSize,
  id,
}: {
  slice: Pick<PageSlice<unknown>, "page" | "pages" | "from" | "to" | "total">;
  size: number;
  onPage: (page: number) => void;
  onSize: (size: number) => void;
  /** Unique per table, for the label. */
  id: string;
}) {
  const { page, pages, from, to, total } = slice;
  return (
    <div className="pager" role="navigation" aria-label="Table pages">
      <label className="muted small" htmlFor={`${id}-size`}>
        Rows per page
      </label>
      <select id={`${id}-size`} className="input pager-size" value={size} onChange={(e) => onSize(Number(e.target.value))}>
        {PAGE_SIZES.map((n) => (
          <option key={n} value={n}>
            {n === 0 ? "All" : n}
          </option>
        ))}
      </select>
      <span className="muted small pager-range">{total ? `${from}–${to} of ${total}` : "0 of 0"}</span>
      {pages > 1 && (
        <span className="pager-nav">
          <button type="button" className="btn ghost small" disabled={page === 0} onClick={() => onPage(0)} aria-label="First page">
            «
          </button>
          <button type="button" className="btn ghost small" disabled={page === 0} onClick={() => onPage(page - 1)}>
            ‹ Prev
          </button>
          <span className="muted small">
            Page {page + 1} of {pages}
          </span>
          <button type="button" className="btn ghost small" disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>
            Next ›
          </button>
          <button type="button" className="btn ghost small" disabled={page >= pages - 1} onClick={() => onPage(pages - 1)} aria-label="Last page">
            »
          </button>
        </span>
      )}
    </div>
  );
}
