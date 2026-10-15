import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { listKeyAction, opensList } from "../dropdownKeys";

export interface MenuAction {
  label: string;
  onSelect: () => void;
  danger?: boolean;
}

/**
 * Row "⋯" menu in the custom dropdown style. The panel is portalled with fixed positioning because the
 * table card scrolls and would clip it; it closes on outside click, Esc, scroll or resize.
 */
export function ActionMenu({ label, header, actions }: { label: string; header: string; actions: MenuAction[] }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [pos, setPos] = useState<{ top: number; right: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLUListElement>(null);

  useLayoutEffect(() => {
    if (!open || !trigger.current) return;
    const r = trigger.current.getBoundingClientRect();
    setPos({ top: r.bottom + 6, right: window.innerWidth - r.right });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !trigger.current?.contains(t)) setOpen(false);
    };
    const dismiss = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("resize", dismiss);
    window.addEventListener("scroll", dismiss, true);
    list.current?.focus();
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("resize", dismiss);
      window.removeEventListener("scroll", dismiss, true);
    };
  }, [open, pos]);

  const close = (focusTrigger: boolean) => {
    setOpen(false);
    if (focusTrigger) trigger.current?.focus();
  };
  const choose = (i: number) => {
    close(true);
    actions[i]?.onSelect();
  };
  const onListKey = (e: KeyboardEvent) => {
    const action = listKeyAction(e.key, active, actions.map((a) => a.label));
    if (action.type === "none") return;
    if (e.key !== "Tab") e.preventDefault();
    if (action.type === "move") setActive(action.index);
    else if (action.type === "select") choose(action.index);
    else close(e.key !== "Tab");
  };

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className={`row-menu-btn ${open ? "open" : ""}`}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          if (open) close(false);
          else {
            setActive(0);
            setOpen(true);
          }
        }}
        onKeyDown={(e) => {
          if (!open && opensList(e.key)) {
            e.preventDefault();
            e.stopPropagation();
            setActive(0);
            setOpen(true);
          }
        }}
      >
        ⋯
      </button>
      {open &&
        pos &&
        createPortal(
          <div
            ref={panel}
            className="dropdown-panel action-panel"
            style={{ top: pos.top, right: pos.right }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dropdown-header" aria-hidden="true">
              {header}
            </div>
            <ul ref={list} role="menu" tabIndex={-1} aria-label={header} aria-activedescendant={`${id}-act-${active}`} onKeyDown={onListKey}>
              {actions.map((a, i) => (
                <li
                  key={a.label}
                  id={`${id}-act-${i}`}
                  role="menuitem"
                  className={`${i === active ? "active" : ""} ${a.danger ? "danger" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choose(i)}
                >
                  {a.label}
                </li>
              ))}
            </ul>
          </div>,
          document.body,
        )}
    </>
  );
}
