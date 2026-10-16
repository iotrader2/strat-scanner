import type { Status } from "../api";
import { refreshProgress } from "../loading";

/** Blue spinner plus pulsing text; announced to screen readers. */
export function LoadingIndicator({ label = "Loading…", className = "" }: { label?: string; className?: string }) {
  return (
    <span className={`loading-indicator ${className}`} role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span className="loading-text">{label}</span>
    </span>
  );
}

/** Placeholder table with shimmering rows, shown while a table's data loads. */
export function SkeletonTable({ rows = 8, cols = 10, label = "Loading…" }: { rows?: number; cols?: number; label?: string }) {
  return (
    <div className="card table-card skeleton-table" aria-busy="true">
      <div className="skeleton-head">
        <LoadingIndicator label={label} />
      </div>
      <table className="scan-table" aria-hidden="true">
        <tbody>
          {Array.from({ length: rows }, (_, r) => (
            <tr key={r}>
              {Array.from({ length: cols }, (_, c) => (
                <td key={c}>
                  <span className={`skeleton-bar ${c === 0 ? "wide" : c % 3 === 1 ? "mid" : ""}`} />
                  {c === 0 && <span className="skeleton-bar sub" />}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Placeholder chart cards (header, badges, chart area, footer) with a shimmer. */
export function SkeletonCards({
  count,
  chartHeight = 180,
  className = "sector-grid",
  label = "Loading charts…",
}: {
  count: number;
  chartHeight?: number;
  className?: string;
  label?: string;
}) {
  return (
    <div aria-busy="true">
      <div className="skeleton-cards-label">
        <LoadingIndicator label={label} />
      </div>
      <div className={className} aria-hidden="true">
        {Array.from({ length: count }, (_, i) => (
          <div key={i} className="card sector-card skeleton-card">
            <div className="skeleton-row">
              <span className="skeleton-bar wide" />
              <span className="skeleton-bar short" />
            </div>
            <div className="skeleton-row">
              <span className="skeleton-bar pill" />
              <span className="skeleton-bar pill" />
              <span className="skeleton-bar pill" />
            </div>
            <div className="skeleton-chart" style={{ height: chartHeight }} />
            <span className="skeleton-bar mid" />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Pulsing banner under the top bar while a data refresh runs, e.g. "Refreshing data… 120/546". */
export function RefreshBanner({ status }: { status: Status | null }) {
  if (!status?.refreshing) return null;
  const p = refreshProgress(status.progress);
  return (
    <div className="refresh-banner" role="status" aria-live="polite">
      <div className="refresh-banner-text">
        <span className="spinner" aria-hidden="true" />
        <span className="loading-text">{p.label}</span>
        {p.detail && <span className="muted small">{p.detail}</span>}
      </div>
      <div
        className={`refresh-track ${p.pct === null ? "indeterminate" : ""}`}
        role="progressbar"
        aria-label="Data refresh progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={p.pct ?? undefined}
      >
        <div className="refresh-fill" style={p.pct === null ? undefined : { width: `${p.pct}%` }} />
      </div>
    </div>
  );
}
