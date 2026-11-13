import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, type ScanRow, type WatchlistHistory } from "../api";
import { usePersisted } from "../persist";
import { SkeletonTable } from "../components/Loading";
import { ListTable } from "../components/ListTable";
import type { ExtraColumn } from "../components/ScanTable";
import { useWatchlist } from "../components/Watch";
import { phoenixStamp } from "../alerts";
import { queueSummary, useSymbolQueue } from "../symbolQueue";
import { normalizeTicker, watchSetupGroups, watchedRows, type WatchSetupGroup } from "../watchlist";

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

export function WatchSetupCell({ setups }: { setups: ScanRow["watch_setups"] }) {
  const groups = watchSetupGroups(setups);
  if (!groups.length) return <span className="muted">—</span>;
  return (
    <span className="watch-setups">
      {groups.map((group) => (
        <WatchSetupLine key={group.side} group={group} />
      ))}
    </span>
  );
}

function WatchSetupLine({ group }: { group: WatchSetupGroup }) {
  return (
    <span className="watch-setup">
      <span className={`side-chip ${group.side}`}>{group.side === "short" ? "SHORT" : "LONG"}</span>
      {group.text}
    </span>
  );
}

const SETUP_COLUMN: ExtraColumn = {
  key: "setup",
  label: "Setup",
  title: "Daily setups that qualified this name for alerts. A dash is a name you added that does not currently qualify.",
  ascendingFirst: true,
  sortValue: (row) => {
    const groups = watchSetupGroups(row.watch_setups);
    return groups.length ? groups.map((group) => `${group.side} ${group.text}`).join(" ") : null;
  },
  render: (row) => <WatchSetupCell setups={row.watch_setups} />,
};

/** Header line for when the post-close load ran, and the smaller time of the last intraday auto-add. */
export function WatchlistLoaded({
  loadedAt,
  updatedAt,
}: {
  loadedAt: string | null | undefined;
  updatedAt: string | null | undefined;
}) {
  return (
    <p className="watchlist-times">
      <span className="watchlist-loaded">Last loaded: {phoenixStamp(loadedAt)}</span>
      <span className="muted small">Last updated: {phoenixStamp(updatedAt)}</span>
    </p>
  );
}

const SOURCE_COLUMN: ExtraColumn = {
  key: "source",
  label: "Added",
  title: "Auto: the alerts put the name on the list. You: you added it by hand.",
  ascendingFirst: true,
  sortValue: (row) => (row as WatchlistHistory["rows"][number]).watch_source ?? null,
  render: (row) => {
    const source = (row as WatchlistHistory["rows"][number]).watch_source;
    return source ? <span className="muted">{source === "alert" ? "Auto" : "You"}</span> : <span className="muted">—</span>;
  },
};

const HISTORY_COLUMNS = [SOURCE_COLUMN, SETUP_COLUMN];

/** Read-only view of the list stored at one day's close. Stored from the post-close reset onward; never backfilled. */
export function WatchlistHistoryView() {
  const [date, setDate] = useState("");
  const [data, setData] = useState<WatchlistHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .watchlistHistory(date || undefined)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
        if (!date && d.date) setDate(d.date);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [date]);

  const rows = data?.rows ?? [];
  const missing = data?.missing ?? [];
  return (
    <>
      <div className="table-meta alerts-toolbar">
        <div className="alerts-toolbar-left">
          <label className="muted small" htmlFor="watchlist-history-date">
            Trading day
          </label>
          <input
            id="watchlist-history-date"
            className="input date"
            type="date"
            value={date}
            max={data?.dates[0]}
            min={data?.dates[data.dates.length - 1]}
            onChange={(e) => setDate(e.target.value)}
          />
          {data && data.date && (
            <span className="muted small">
              {data.symbols.length} names{data.dates.length > 1 ? ` · ${data.dates.length} days kept` : ""}
            </span>
          )}
        </div>
        <span className="muted small">
          {data?.snapshot_at ? `Saved ${phoenixStamp(data.snapshot_at)}. ` : ""}Prices as of that close. Read only.
        </span>
      </div>
      {error && <div className="banner error">{error}</div>}
      {missing.length > 0 && <div className="banner">No scan data was saved for {missing.join(", ")} that day.</div>}
      {data === null ? (
        <SkeletonTable rows={5} cols={13} label="Loading history…" />
      ) : data.dates.length === 0 ? (
        <div className="card empty-state">
          No watchlist history yet. The list is saved each trading day at the close (4:01 PM New York), starting from
          the next close.
        </div>
      ) : data.symbols.length === 0 ? (
        <div className="card empty-state">No watchlist saved{data.date ? ` for ${data.date}` : ""}.</div>
      ) : (
        <ListTable rows={rows} intraday={undefined} extraColumns={HISTORY_COLUMNS} />
      )}
    </>
  );
}

export default function Watchlist() {
  const [view, setView] = usePersisted<"current" | "history">("watchlistView", "current");
  return (
    <div className="page">
      {view === "current" ? <CurrentWatchlist /> : (
        <section className="hero">
          <div>
            <h1>Watchlist</h1>
            <p className="muted">The list as it stood at the close of a past trading day.</p>
          </div>
        </section>
      )}
      <div className="alerts-tabs">
        <div className="seg" role="tablist">
          <button type="button" role="tab" aria-selected={view === "current"} className={view === "current" ? "active" : ""} onClick={() => setView("current")}>
            Current
          </button>
          <button type="button" role="tab" aria-selected={view === "history"} className={view === "history" ? "active" : ""} onClick={() => setView("history")}>
            History
          </button>
        </div>
      </div>
      {view === "current" ? <CurrentWatchlistTable /> : <WatchlistHistoryView />}
    </div>
  );
}

function CurrentWatchlist() {
  const { symbols, data } = useWatchlist();
  const rows = useMemo(() => watchedRows(data?.rows ?? [], symbols), [data, symbols]);
  const active = rows.filter((r) => r.has_setup).length;
  return (
    <section className="hero">
      <div>
        <h1>Watchlist</h1>
        <WatchlistLoaded loadedAt={data?.loaded_at} updatedAt={data?.updated_at} />
        <p className="muted">
          Stocks you&apos;re watching. They stay until you take them off. Setup is the daily setup that put an
          auto-added name on the list. A dash is a name you added that does not currently qualify. When you buy
          one, use Bought on Alerts.
        </p>
      </div>
      <div className="stat-cards">
        <div className="stat-card">
          <span className="stat-value">{symbols.length}</span>
          <span className="stat-label">watched</span>
        </div>
        <div className="stat-card">
          <span className="stat-value accent-text">{active}</span>
          <span className="stat-label">with a daily setup</span>
        </div>
      </div>
    </section>
  );
}

function CurrentWatchlistTable() {
  const { symbols, data, error } = useWatchlist();
  const rows = useMemo(() => watchedRows(data?.rows ?? [], symbols), [data, symbols]);
  const missing = (data?.missing ?? []).filter((s) => symbols.includes(s));

  return (
    <>
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
        <ListTable rows={rows} intraday={data?.intraday} extraColumns={[SETUP_COLUMN]} />
      )}
    </>
  );
}
