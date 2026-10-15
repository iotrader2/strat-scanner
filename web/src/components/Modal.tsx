import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { parseEntry, todayIso, type EntryForm } from "../positions";

/** Centered panel in the dropdown style. Esc or a click on the backdrop closes it; focus returns to the opener. */
export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
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
      <div className="modal-panel" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} ref={panel} tabIndex={-1}>
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
}: {
  title: string;
  symbol: string;
  initial: { price: number | null; shares: number | null; date?: string };
  lastPrice: number | null;
  submitLabel: string;
  onSubmit: (values: EntryValues) => Promise<void>;
  onClose: () => void;
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
          <span className="field-label">Entry price</span>
          <input className="input" inputMode="decimal" value={form.price} onChange={set("price")} autoFocus autoComplete="off" />
        </label>
        <label className="entry-field">
          <span className="field-label">
            Shares <span className="optional">optional</span>
          </span>
          <input className="input" inputMode="decimal" value={form.shares} onChange={set("shares")} placeholder="—" autoComplete="off" />
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
