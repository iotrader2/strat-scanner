import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Legend } from "../components/Badges";
import { ScanTable } from "../components/ScanTable";
import { useWatchlist } from "../components/Watch";
import { watchedRows } from "../watchlist";

export default function Watchlist() {
  const { symbols, data, error } = useWatchlist();
  const rows = useMemo(() => watchedRows(data?.rows ?? [], symbols), [data, symbols]);
  const missing = (data?.missing ?? []).filter((s) => symbols.includes(s));
  const active = rows.filter((r) => r.has_setup).length;

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Watchlist</h1>
          <p className="muted">
            Names you are tracking, with the same Strat badges, weekly trigger and score as the Stock Scanner. They stay here
            when the weekly setup goes away (shown as “no active setup”) until you remove them. Saved in the local
            SQLite cache, so the list survives restarts.
          </p>
        </div>
        <div className="stat-cards">
          <div className="stat-card">
            <span className="stat-value">{symbols.length}</span>
            <span className="stat-label">watched</span>
          </div>
          <div className="stat-card">
            <span className="stat-value accent-text">{active}</span>
            <span className="stat-label">with a weekly setup</span>
          </div>
        </div>
      </section>

      <div className="table-meta">
        <span className="muted">{data === null ? "Loading…" : `${rows.length} watched names`}</span>
        <Legend />
      </div>
      {error && <div className="banner error">{error}</div>}
      {missing.length > 0 && (
        <div className="banner">No cached data yet for {missing.join(", ")}; they appear after the next refresh.</div>
      )}
      {data !== null && symbols.length === 0 ? (
        <div className="card empty-state">
          Your watchlist is empty. Use the <span className="watch-btn inline">+</span> button on a{" "}
          <Link className="sector-link" to="/">Stock Scanner</Link> row, a stock page or a{" "}
          <Link className="sector-link" to="/sectors">sector</Link> card to add names.
        </div>
      ) : (
        <ScanTable rows={rows} removable />
      )}
    </div>
  );
}
