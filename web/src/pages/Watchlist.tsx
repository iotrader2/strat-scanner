import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { ScanRow } from "../api";
import { Legend } from "../components/Badges";
import { SkeletonTable } from "../components/Loading";
import { EntryModal } from "../components/Modal";
import { usePositions } from "../components/Positions";
import { ScanTable } from "../components/ScanTable";
import { useWatchlist } from "../components/Watch";
import { normalizeTicker, watchedRows } from "../watchlist";

function AddSymbol() {
  const { add, isWatched } = useWatchlist();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const symbol = normalizeTicker(value);
    if (!symbol || busy) return;
    if (isWatched(symbol)) {
      setMessage({ ok: true, text: `${symbol} is already on your watchlist` });
      return;
    }
    setBusy(symbol);
    setMessage(null);
    try {
      await add(symbol);
      setValue("");
      setMessage({ ok: true, text: `Added ${symbol}` });
    } catch (err) {
      setMessage({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <form className="card add-symbol" onSubmit={submit}>
      <label htmlFor="add-symbol-input">Add symbol</label>
      <input
        id="add-symbol-input"
        className="input"
        placeholder="Any ticker, e.g. MRNA"
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        autoComplete="off"
        spellCheck={false}
        maxLength={16}
        disabled={busy !== null}
      />
      <button className="btn" type="submit" disabled={busy !== null || !normalizeTicker(value)}>
        {busy ? `Adding ${busy}…` : "+ Add"}
      </button>
      {message && <span className={message.ok ? "muted small" : "red-text small"}>{message.text}</span>}
      <span className="muted small add-hint">
        Any Yahoo Finance ticker works; names outside the S&amp;P 500 / Nasdaq-100 are downloaded, scored and refreshed
        while they are on the list.
      </span>
    </form>
  );
}

export default function Watchlist() {
  const { symbols, data, error } = useWatchlist();
  const { open } = usePositions();
  const [moving, setMoving] = useState<ScanRow | null>(null);
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
            when the weekly setup goes away (shown as “no active setup”) until you remove them with the first-column ✓ toggle. Once you buy one, use “Move to Positions” to record the entry and
            track it on the Positions tab. Saved in the local
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

      <AddSymbol />

      <div className="table-meta">
        {data !== null && <span className="muted">{`${rows.length} watched names`}</span>}
        <Legend />
      </div>
      {error && <div className="banner error">{error}</div>}
      {missing.length > 0 && (
        <div className="banner">No cached data yet for {missing.join(", ")}; they appear after the next refresh.</div>
      )}
      {data !== null && symbols.length === 0 ? (
        <div className="card empty-state">
          Your watchlist is empty. Type a ticker above, or use the <span className="watch-btn inline">+</span> button on a{" "}
          <Link className="sector-link" to="/">Stock Scanner</Link> row, a stock page or a{" "}
          <Link className="sector-link" to="/themes">theme</Link> card to add names.
        </div>
      ) : data === null ? (
        <SkeletonTable rows={5} cols={16} label="Loading watchlist…" />
      ) : (
        <ScanTable
          rows={rows}
          actionsLabel="Bought?"
          actions={(r) => (
            <button type="button" className="btn small move-btn" onClick={() => setMoving(r)} title="Record the entry and track it on the Positions tab">
              Move to Positions →
            </button>
          )}
        />
      )}
      {moving && (
        <EntryModal
          title="Move to Positions"
          symbol={moving.symbol}
          initial={{ price: moving.price, shares: null }}
          lastPrice={moving.price}
          submitLabel="Move to Positions"
          onSubmit={(v) => open(moving.symbol, v)}
          onClose={() => setMoving(null)}
        />
      )}
    </div>
  );
}
