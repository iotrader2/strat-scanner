import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { listKeyAction, opensList } from "../dropdownKeys";

export interface DropdownOption<T extends string> {
  value: T;
  label: string;
}

interface Props<T extends string> {
  /** Field label shown above the trigger, e.g. "Sector". */
  label: string;
  /** Small uppercase header inside the open panel, e.g. "Filter by sector". */
  header: string;
  value: T;
  options: DropdownOption<T>[];
  onChange: (value: T) => void;
}

/** Custom select: dark rounded panel, check on the selected option, full keyboard support, closes on outside click/Esc. */
export function Dropdown<T extends string>({ label, header, value, options, onChange }: Props<T>) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const selectedIndex = Math.max(0, options.findIndex((o) => o.value === value));
  const selected = options[selectedIndex];

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    list.current?.focus();
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (open) list.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active]);

  const openList = () => {
    setActive(selectedIndex);
    setOpen(true);
  };

  const close = (focusTrigger: boolean) => {
    setOpen(false);
    if (focusTrigger) trigger.current?.focus();
  };

  const choose = (index: number) => {
    const option = options[index];
    if (option) onChange(option.value);
    close(true);
  };

  const onTriggerKey = (e: KeyboardEvent) => {
    if (!open && opensList(e.key)) {
      e.preventDefault();
      openList();
    }
  };

  const onListKey = (e: KeyboardEvent) => {
    const action = listKeyAction(e.key, active, options.map((o) => o.label));
    if (action.type === "none") return;
    if (e.key !== "Tab") e.preventDefault();
    if (action.type === "move") setActive(action.index);
    else if (action.type === "select") choose(action.index);
    else close(e.key !== "Tab");
  };

  return (
    <div className="field dropdown" ref={root}>
      <span className="field-label" id={`${id}-label`}>
        {label}
      </span>
      <button
        ref={trigger}
        type="button"
        className={`dropdown-trigger ${open ? "open" : ""}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${id}-label ${id}-value`}
        onClick={() => (open ? close(false) : openList())}
        onKeyDown={onTriggerKey}
      >
        <span id={`${id}-value`} className="dropdown-value">
          {selected?.label}
        </span>
        <svg className="dropdown-chevron" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="dropdown-panel">
          <div className="dropdown-header" aria-hidden="true">
            {header}
          </div>
          <ul
            ref={list}
            role="listbox"
            tabIndex={-1}
            aria-label={header}
            aria-activedescendant={`${id}-opt-${active}`}
            onKeyDown={onListKey}
          >
            {options.map((o, i) => (
              <li
                key={o.value}
                id={`${id}-opt-${i}`}
                data-index={i}
                role="option"
                aria-selected={o.value === value}
                className={`${o.value === value ? "selected" : ""} ${i === active ? "active" : ""}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(i)}
              >
                <span>{o.label}</span>
                {o.value === value && (
                  <svg className="dropdown-check" viewBox="0 0 16 16" aria-hidden="true">
                    <path d="M3.5 8.5 6.5 11.5 12.5 4.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
