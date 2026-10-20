import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { Position } from "../api";
import {
  formatBreakEven,
  fmtPnl,
  fmtShares,
  fmtTrimWhen,
  parseEntry,
  parseTrim,
  todayIso,
  trimPreview,
  type EntryForm,
  type TrimForm,
} from "../positions";

/** Centered panel in the dropdown style. Esc or a click on the backdrop closes it; focus returns to the opener. */
export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    if (!panel.current?.contains(document.activeElement)) panel.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, []);

  // Portalled out of the table; React still bubbles events to the row, so stop clicks from opening the stock page.
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()} onClick={(e) => e.stopPropagation()}>
      <div className={`modal-panel${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} ref={panel} tabIndex={-1}>
        <div className="modal-head">
          <div className="dropdown-header" id={`${id}-title`}>
            {title}
          </div>
          <button type="button" className="modal-x" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export interface EntryValues {
  entry_price: number | null;
  shares: number | null;
  entry_date: string;
}

/** Entry price / shares / entry date form, used to move a name into Positions and to edit a position. */
export function EntryModal({
  title,
  symbol,
  initial,
  lastPrice,
  submitLabel,
  onSubmit,
  onClose,
  sharesNote,
}: {
  title: string;
  symbol: string;
  initial: { price: number | null; shares: number | null; date?: string };
  lastPrice: number | null;
  submitLabel: string;
  onSubmit: (values: EntryValues) => Promise<void>;
  onClose: () => void;
  sharesNote?: string;
}) {
  const today = todayIso();
  const [form, setForm] = useState<EntryForm>({
    price: initial.price !== null ? String(initial.price) : "",
    shares: initial.shares !== null ? String(initial.shares) : "",
    date: initial.date ?? today,
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof EntryForm) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const parsed = parseEntry(form, today);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(parsed);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <Modal title={title} onClose={onClose}>
      <form className="entry-form" onSubmit={submit}>
        <div className="entry-symbol">
          {symbol}
          {lastPrice !== null && <span className="muted small">last {lastPrice.toFixed(2)}</span>}
        </div>
        <label className="entry-field">
          <span className="field-label">Buy price</span>
          <input className="input" inputMode="decimal" value={form.price} onChange={set("price")} autoFocus autoComplete="off" />
        </label>
        <label className="entry-field">
          <span className="field-label">
            Shares <span className="optional">optional</span>
          </span>
          <input className="input" inputMode="decimal" value={form.shares} onChange={set("shares")} placeholder="—" autoComplete="off" />
          {sharesNote && <span className="muted small">{sharesNote}</span>}
        </label>
        <label className="entry-field">
          <span className="field-label">Entry date</span>
          <input className="input" type="date" value={form.date} max={today} onChange={set("date")} />
        </label>
        {error && <div className="red-text small">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? "Saving…" : submitLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const signClass = (v: number) => (v > 0 ? "green-text" : v < 0 ? "red-text" : "muted");

/** Partial sell: price and shares, with a live preview of what the position becomes. */
export function TrimModal({
  position,
  lastPrice,
  onSubmit,
  onUndo,
  onClose,
}: {
  position: Position;
  lastPrice: number | null;
  onSubmit: (values: { price: number; shares: number }) => Promise<void>;
  onUndo: (trimId: number) => Promise<void>;
  onClose: () => void;
}) {
  const remaining = position.remaining_shares;
  const [form, setForm] = useState<TrimForm>({
    price: lastPrice !== null ? String(lastPrice) : "",
    shares: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [undoing, setUndoing] = useState<number | null>(null);
  const set = (key: keyof TrimForm) => (e: { target: { value: string } }) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
    setError(null);
  };

  const parsed = parseTrim(form, remaining);
  const preview =
    parsed.ok && position.shares
      ? trimPreview(
          { entry_price: position.entry_price, initial_shares: position.shares, trims: position.trims },
          parsed,
        )
      : null;
  const basis = preview ? formatBreakEven(preview.breakEven) : null;
  const needsShares = remaining === null || !(remaining > 0);
  const liveError = needsShares
    ? "Add a share count before trimming (use Edit entry)"
    : form.price.trim() && form.shares.trim() && !parsed.ok
      ? parsed.error
      : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit(parsed);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const undo = async (trimId: number) => {
    setUndoing(trimId);
    setError(null);
    try {
      await onUndo(trimId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUndoing(null);
    }
  };

  return (
    <Modal title="Trim" onClose={onClose} wide>
      <form className="entry-form" onSubmit={submit}>
        <div className="entry-symbol">
          {position.symbol}
          <span className="muted small">
            {remaining === null ? "no share count" : `${fmtShares(remaining)} shares left`}
            {lastPrice !== null && ` · last ${lastPrice.toFixed(2)}`}
          </span>
        </div>
        <label className="entry-field">
          <span className="field-label">Trim price</span>
          <input className="input" inputMode="decimal" value={form.price} onChange={set("price")} autoFocus autoComplete="off" />
        </label>
        <label className="entry-field">
          <span className="field-label">Shares to trim</span>
          <input className="input" inputMode="decimal" value={form.shares} onChange={set("shares")} placeholder="—" autoComplete="off" />
        </label>
        <div className="trim-preview" aria-live="polite">
          <span className="muted">Remaining</span>
          <span>{preview ? `${fmtShares(preview.remaining)} shares` : "—"}</span>
          <span className="muted">Realized P/L</span>
          <span className={preview ? signClass(preview.realized) : "muted"}>{preview ? fmtPnl(preview.realized) : "—"}</span>
          <span className="muted">Break-even</span>
          <span>
            {basis ? basis.label : "—"}
            {basis?.note && <span className="free-note"> {basis.note}</span>}
          </span>
        </div>
        {position.trims.length > 0 && (
          <div className="trim-history-wrap">
            <div className="field-label">Trim history</div>
            <ul className="trim-history">
              {position.trims.map((t) => (
                <li key={t.id}>
                  <span>
                    {fmtTrimWhen(t.trimmed_at)} · {fmtShares(t.shares)} sh @ {t.price.toFixed(2)}
                  </span>
                  <button type="button" className="btn small ghost" onClick={() => undo(t.id)} disabled={undoing !== null || busy}>
                    {undoing === t.id ? "Undoing…" : "Undo"}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(error ?? liveError) && <div className="red-text small">{error ?? liveError}</div>}
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy || !preview}>
            {busy ? "Saving…" : "Trim"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function ConfirmModal({
  title,
  message,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  title: string;
  message: ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };
  return (
    <Modal title={title} onClose={onClose}>
      <p className="confirm-text">{message}</p>
      {error && <div className="red-text small">{error}</div>}
      <div className="modal-actions">
        <button type="button" className="btn ghost" onClick={onClose} autoFocus>
          Cancel
        </button>
        <button type="button" className="btn danger" onClick={confirm} disabled={busy}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
