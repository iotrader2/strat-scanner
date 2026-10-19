import { useState } from "react";
import { createPortal } from "react-dom";
import type { ScanRow } from "../api";
import { formatWeight } from "../leadership";

type ScoreFields = Pick<ScanRow, "score" | "score_raw" | "score_max_raw" | "score_breakdown">;

const fmt = (v: number) => (Math.abs(v) < 0.05 ? "0" : v.toFixed(1).replace(/\.0$/, ""));

/** Green once a line earns half of what it is worth; a penalty or a weak share is red. */
function scoreTone(points: number, max: number): "good" | "bad" {
  if (max > 0) return points / max >= 0.5 ? "good" : "bad";
  return points < 0 ? "bad" : "good";
}

export function BreakdownTable({ row, showDetail = false }: { row: ScoreFields; showDetail?: boolean }) {
  const parts = [...row.score_breakdown].sort((a, b) => b.weight_pct - a.weight_pct);
  const totalTone = scoreTone(row.score_raw, row.score_max_raw);
  return (
    <table className="breakdown">
      <tbody>
        {parts.map((c) => (
          <tr key={c.key} className={scoreTone(c.points, c.max_points)}>
            <td>
              <div className="bd-label">
                {c.label}
                {c.weight_pct > 0 && <span className="bd-weight"> ({formatWeight(c.weight_pct)})</span>}
              </div>
              {c.sub_weights?.length > 0 && <div className="bd-sub">{c.sub_weights.join(" · ")}</div>}
              {showDetail && <div className="bd-detail">{c.detail}</div>}
            </td>
            <td className="num bd-pts">
              {c.points > 0 ? "+" : ""}
              {fmt(c.points)}
              {c.max_points > 0 && <span className="bd-max"> / {c.max_points}</span>}
            </td>
          </tr>
        ))}
        <tr className={`bd-total ${totalTone}`}>
          <td>Raw total</td>
          <td className="num">
            {fmt(row.score_raw)}
            <span className="bd-max"> / {row.score_max_raw}</span>
          </td>
        </tr>
        <tr className={`bd-score ${totalTone}`}>
          <td>
            Score <span className="bd-max">= raw × 100 / {row.score_max_raw}</span>
          </td>
          <td className="num">{row.score.toFixed(1)}</td>
        </tr>
      </tbody>
    </table>
  );
}

export function ScorePill({ score, row }: { score: number; row?: ScoreFields }) {
  const [pos, setPos] = useState<{ x: number; y: number; above: boolean } | null>(null);
  const level = score >= 70 ? "hi" : score >= 50 ? "mid" : "lo";

  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    const above = r.bottom + 440 > window.innerHeight;
    setPos({ x: Math.min(r.right, window.innerWidth - 12), y: above ? r.top - 8 : r.bottom + 8, above });
  };

  return (
    <>
      <span
        className={`score-pill ${level} ${row ? "has-breakdown" : ""}`}
        tabIndex={row ? 0 : undefined}
        onMouseEnter={row ? (e) => show(e.currentTarget) : undefined}
        onMouseLeave={() => setPos(null)}
        onFocus={row ? (e) => show(e.currentTarget) : undefined}
        onBlur={() => setPos(null)}
      >
        {score.toFixed(0)}
      </span>
      {row && pos &&
        createPortal(
          <div
            className="score-tooltip"
            role="tooltip"
            style={{ left: pos.x, top: pos.y, transform: `translate(-100%, ${pos.above ? "-100%" : "0"})` }}
          >
            <div className="tt-title">Score breakdown</div>
            <BreakdownTable row={row} />
          </div>,
          document.body,
        )}
    </>
  );
}
