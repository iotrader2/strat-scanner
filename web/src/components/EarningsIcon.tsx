import { useState } from "react";
import { createPortal } from "react-dom";
import type { Earnings } from "../api";
import { earningsLines } from "../earnings";

/** ⚠ shown when the stock reports within the next 10 calendar days; hover or focus for date and timing. */
export function EarningsIcon({ earnings }: { earnings: Earnings | null | undefined }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  if (!earnings) return null;
  const lines = earningsLines(earnings);

  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    setPos({ x: Math.min(r.left, window.innerWidth - 280), y: r.bottom + 6 });
  };

  return (
    <>
      <span
        className="earnings-icon"
        tabIndex={0}
        role="img"
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
          <div className="earnings-tooltip" role="tooltip" style={{ left: pos.x, top: pos.y }}>
            <div className="tt-title">Earnings soon</div>
            {lines.map((l) => (
              <div key={l}>{l}</div>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
