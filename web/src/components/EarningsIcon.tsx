import { useState } from "react";
import { createPortal } from "react-dom";
import type { Earnings } from "../api";
import { earningsLines } from "../earnings";

/** ⚠ shown when the server flags earnings inside the user's warning window (calendar days, today included). */
export function EarningsIcon({ earnings }: { earnings: Earnings | null | undefined }) {
  const [pos, setPos] = useState<{ x: number; y: number; above: boolean } | null>(null);
  if (!earnings) return null;
  const lines = earningsLines(earnings);

  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    const above = r.bottom + 72 > window.innerHeight;
    setPos({ x: r.left, y: above ? r.top - 8 : r.bottom + 8, above });
  };

  return (
    <>
      <span
        className="earnings-icon"
        role="img"
        tabIndex={0}
        aria-label={lines.join(", ")}
        onMouseEnter={(e) => show(e.currentTarget)}
        onMouseLeave={() => setPos(null)}
        onFocus={(e) => show(e.currentTarget)}
        onBlur={() => setPos(null)}
        onClick={(e) => e.stopPropagation()}
      >
        ⚠
      </span>
      {pos &&
        createPortal(
          <div
            className="earnings-tooltip"
            role="tooltip"
            style={{ left: pos.x, top: pos.y, transform: `translate(0, ${pos.above ? "-100%" : "0"})` }}
          >
            <div className="tt-title">{lines[0]}</div>
            <div>{lines[1]}</div>
          </div>,
          document.body,
        )}
    </>
  );
}
