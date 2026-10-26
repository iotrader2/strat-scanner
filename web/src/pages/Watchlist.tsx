import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { ScanRow } from "../api";
import { SkeletonTable } from "../components/Loading";
import { EntryModal } from "../components/Modal";
import { usePositions } from "../components/Positions";
import { ListTable } from "../components/ListTable";
import { useWatchlist } from "../components/Watch";
import { queueSummary, useSymbolQueue } from "../symbolQueue";
import { normalizeTicker, watchedRows } from "../watchlist";

/** Add-any-ticker box. Enter queues the ticker, clears the field and keeps focus, so SPY ⏎ QQQ ⏎ works without clicking back. */
export function AddSymbol() {
  const { add, isWatched } = useWatchlist();
  const [value, setValue] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { enqueue, pending, result, isPending } = useSymbolQueue<null>((symbol) => add(symbol));
  const summary = queueSummary(result, "Added");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    // Synchronously, inside the key / click handler: iPad Safari only keeps the keyboard up for a focus() made here.
    inputRef.current?.focus();
    const symbol = normalizeTicker(value);
    if (!symbol) return;
    setValue("");
    if (isWatched(symbol)) {
      setNote(`${symbol} is already on your watchlist`);
      return;
    }
    if (isPending(symbol)) {
      setNote(`${symbol} is already being added`);
      return;
    }
    setNote(null);
    enqueue(symbol, null);
  };

  return (
    <form className="card add-symbol" onSubmit={submit}>
      <label htmlFor="add-symbol-input">Add symbol</label>
      <input
        ref={inputRef}
        id="add-symbol-input"
        className="input"
        placeholder="Any ticker, e.g. MRNA"
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        autoComplete="off"
        autoCapitalize="characters"
        spellCheck={false}
        enterKeyHint="enter"
        maxLength={16}
      />
      <button className="btn" type="submit" disabled={!normalizeTicker(value)}>
        + Add
      </button>
      {pending.length > 0 && <span className="muted small">Adding {pending.join(", ")}…</span>}
      {note && <span className="muted small">{note}</span>}
      {summary.ok && <span className="muted small">{summary.ok}</span>}
      {summary.error && <span className="red-text small">{summary.error}</span>}
      <span className="muted small add-hint">
        Any Yahoo Finance ticker works; names outside the S&amp;P 500 / Nasdaq-100 are downloaded, scored and kept
        up to date while they are on the list.
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
            Stocks you&apos;re watching. They stay until you take them off. When you buy one, move it to Positions.
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
      </div>
      {error && <div className="banner error">{error}</div>}
      {missing.length > 0 && (
        <div className="banner">No cached data yet for {missing.join(", ")}; they appear once their history is downloaded.</div>
      )}
      {data !== null && symbols.length === 0 ? (
        <div className="card empty-state">
          Your watchlist is empty. Type a ticker above, or use the <span className="watch-btn inline">+</span> button on a{" "}
          <Link className="sector-link" to="/">Stock Scanner</Link> row, a stock page or a{" "}
          <Link className="sector-link" to="/themes">theme</Link> card to add names.
        </div>
      ) : data === null ? (
        <SkeletonTable rows={5} cols={13} label="Loading watchlist…" />
      ) : (
        <ListTable
          rows={rows}
          intraday={data?.intraday}
          actionsLabel=""
          pinActions={false}
          actions={(r) => (
            <button type="button" className="btn small move-btn" onClick={() => setMoving(r)} title="Record the entry and track it on the Positions tab">
              Bought →
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
