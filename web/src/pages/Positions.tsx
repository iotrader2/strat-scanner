import { useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import type { Position, ScanRow } from "../api";
import { ActionMenu } from "../components/ActionMenu";
import { Legend } from "../components/Badges";
import { SkeletonTable } from "../components/Loading";
import { ConfirmModal, EntryModal } from "../components/Modal";
import { usePositions } from "../components/Positions";
import { ScanTable, type ExtraColumn } from "../components/ScanTable";
import { fmtPct } from "../api";
import { fmtPnl, parseEntry, positionStats, todayIso, type EntryForm } from "../positions";
import { normalizeTicker } from "../watchlist";

function AddPosition() {
  const { open, isHeld } = usePositions();
  const today = todayIso();
  const blank: EntryForm & { symbol: string } = { symbol: "", price: "", shares: "", date: today };
  const [form, setForm] = useState(blank);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: key === "symbol" ? e.target.value.toUpperCase() : e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const symbol = normalizeTicker(form.symbol);
    if (!symbol || busy) return;
    if (isHeld(symbol)) {
      setMessage({ ok: true, text: `${symbol} is already in Positions` });
      return;
    }
    const parsed = parseEntry(form, today, true);
    if (!parsed.ok) {
      setMessage({ ok: false, text: parsed.error });
      return;
    }
    setBusy(symbol);
    setMessage(null);
    try {
      await open(symbol, parsed);
      setForm(blank);
      setMessage({ ok: true, text: `Opened ${symbol}` });
    } catch (err) {
      setMessage({ ok: false, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <form className="card add-symbol add-position" onSubmit={submit}>
      <label htmlFor="add-position-input">Add position</label>
      <input
        id="add-position-input"
        className="input"
        placeholder="Any ticker, e.g. NVDA"
        value={form.symbol}
        onChange={set("symbol")}
        autoComplete="off"
        spellCheck={false}
        maxLength={16}
        disabled={busy !== null}
      />
      <input className="input num-input" inputMode="decimal" placeholder="Entry (last price)" aria-label="Entry price" value={form.price} onChange={set("price")} disabled={busy !== null} />
      <input className="input num-input" inputMode="decimal" placeholder="Shares (optional)" aria-label="Shares" value={form.shares} onChange={set("shares")} disabled={busy !== null} />
      <input className="input date-input" type="date" aria-label="Entry date" value={form.date} max={today} onChange={set("date")} disabled={busy !== null} />
      <button className="btn" type="submit" disabled={busy !== null || !normalizeTicker(form.symbol)}>
        {busy ? `Adding ${busy}…` : "+ Add"}
      </button>
      {message && <span className={message.ok ? "muted small" : "red-text small"}>{message.text}</span>}
    </form>
  );
}

const signClass = (v: number) => (v > 0 ? "green-text" : v < 0 ? "red-text" : "muted");

function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

type Dialog = { kind: "edit" | "close"; position: Position } | null;

export default function Positions() {
  const { data, error, update, close, toWatchlist } = usePositions();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const today = todayIso();
  const held = useMemo(() => data?.positions ?? [], [data]);
  const bySymbol = useMemo(() => new Map(held.map((p) => [p.symbol, p])), [held]);
  const rows = useMemo(() => held.flatMap((p) => (p.row ? [p.row] : [])), [held]);
  const missing = held.filter((p) => !p.row).map((p) => p.symbol);

  const stats = (r: ScanRow) => {
    const p = bySymbol.get(r.symbol);
    return p ? positionStats(p, r.price, today) : null;
  };
  const totals = useMemo(() => {
    let pnl = 0;
    let withShares = 0;
    let winners = 0;
    for (const p of held) {
      if (!p.row) continue;
      const s = positionStats(p, p.row.price, today);
      if (s.pct > 0) winners++;
      if (s.pnl !== null) {
        pnl += s.pnl;
        withShares++;
      }
    }
    return { pnl, withShares, winners };
  }, [held, today]);

  const lead: ExtraColumn[] = [
    {
      key: "entry_price",
      label: "Entry · date",
      className: "num",
      sortValue: (r) => bySymbol.get(r.symbol)?.entry_price ?? null,
      render: (r) => {
        const p = bySymbol.get(r.symbol);
        return (
          p && (
            <>
              <div>{p.entry_price.toFixed(2)}</div>
              <div className="sub muted" title="Entry date">
                {fmtDate(p.entry_date)}
              </div>
            </>
          )
        );
      },
    },
  ];
  const extra: ExtraColumn[] = [
    {
      key: "gain_pct",
      label: "% G/L",
      className: "num",
      sortValue: (r) => stats(r)?.pct ?? null,
      render: (r) => {
        const s = stats(r);
        return s && <span className={`gl-pct ${signClass(s.pct)}`}>{fmtPct(s.pct, 2)}</span>;
      },
    },
    {
      key: "pnl",
      label: "$ P/L",
      className: "num",
      sortValue: (r) => stats(r)?.pnl ?? null,
      render: (r) => {
        const s = stats(r);
        const shares = bySymbol.get(r.symbol)?.shares;
        if (!s || s.pnl === null) return <span className="muted">—</span>;
        return (
          <>
            <div className={signClass(s.pnl)}>{fmtPnl(s.pnl)}</div>
            <div className="sub muted">{shares?.toLocaleString()} sh</div>
          </>
        );
      },
    },
    {
      key: "days_held",
      label: "Days held",
      className: "num",
      sortValue: (r) => stats(r)?.days ?? null,
      render: (r) => {
        const s = stats(r);
        return s && `${s.days}d`;
      },
    },
  ];

  const moveBack = async (p: Position) => {
    try {
      await toWatchlist(p.symbol);
      setNotice(`Moved ${p.symbol} back to the Watchlist`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Positions</h1>
          <p className="muted">
            Stocks you bought. Move one here from the Watchlist after you buy, or add a ticker below. Use the ⋯ menu to
            edit it, send it back, or close it.
          </p>
        </div>
        <div className="stat-cards">
          <div className="stat-card">
            <span className="stat-value">{held.length}</span>
            <span className="stat-label">open</span>
          </div>
          <div className="stat-card">
            <span className="stat-value green-text">{totals.winners}</span>
            <span className="stat-label">in profit</span>
          </div>
          <div className="stat-card">
            <span className={`stat-value ${totals.withShares ? signClass(totals.pnl) : "muted"}`}>
              {totals.withShares ? fmtPnl(totals.pnl) : "—"}
            </span>
            <span className="stat-label">open $ P/L</span>
          </div>
        </div>
      </section>

      <AddPosition />

      <div className="table-meta">
        {data !== null && <span className="muted">{`${held.length} open positions`}</span>}
        <Legend />
      </div>
      {error && <div className="banner error">{error}</div>}
      {notice && <div className="banner">{notice}</div>}
      {missing.length > 0 && (
        <div className="banner">No cached data yet for {missing.join(", ")}; they appear after the next refresh.</div>
      )}
      {data !== null && held.length === 0 ? (
        <div className="card empty-state">
          No open positions. Add a ticker above, or use “Move to Positions” on a{" "}
          <Link className="sector-link" to="/watchlist">Watchlist</Link> row once you buy it.
        </div>
      ) : data === null ? (
        <SkeletonTable rows={4} cols={19} label="Loading positions…" />
      ) : (
        <ScanTable
          rows={rows}
          watchColumn={false}
          priceLabel="Last"
          leadColumns={lead}
          extraColumns={extra}
          actionsLabel=""
          actions={(r) => {
            const p = bySymbol.get(r.symbol);
            if (!p) return null;
            return (
              <ActionMenu
                label={`Actions for ${p.symbol}`}
                header={p.symbol}
                actions={[
                  { label: "Edit entry…", onSelect: () => setDialog({ kind: "edit", position: p }) },
                  { label: "Move back to Watchlist", onSelect: () => moveBack(p) },
                  { label: "Close position…", danger: true, onSelect: () => setDialog({ kind: "close", position: p }) },
                ]}
              />
            );
          }}
        />
      )}

      {dialog?.kind === "edit" && (
        <EntryModal
          title="Edit position"
          symbol={dialog.position.symbol}
          initial={{ price: dialog.position.entry_price, shares: dialog.position.shares, date: dialog.position.entry_date }}
          lastPrice={dialog.position.row?.price ?? null}
          submitLabel="Save"
          onSubmit={(v) => update(dialog.position.symbol, { entry_price: v.entry_price!, shares: v.shares, entry_date: v.entry_date })}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.kind === "close" && (
        <ConfirmModal
          title="Close position"
          message={
            <>
              Close <strong>{dialog.position.symbol}</strong> and remove it from Positions? Its entry details are deleted.
            </>
          }
          confirmLabel="Close position"
          onConfirm={async () => {
            await close(dialog.position.symbol);
            setNotice(`Closed ${dialog.position.symbol}`);
          }}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
