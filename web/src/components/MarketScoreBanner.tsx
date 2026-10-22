import type { Trend } from "../api";
import { marketScoreBreakdown, marketScoreRead } from "../market";

/** Market score out of 6 (QQQ, SPY, IWM × 2): price above the 6-day SMA, and the 6-day above the 20-day. */
export function MarketScoreBanner({ trend }: { trend: Pick<Trend, "score" | "score_max" | "indexes"> }) {
  const read = marketScoreRead(trend.score, trend.score_max);
  const color = `hsl(${read.hue}, 85%, 55%)`;
  return (
    <section
      className="card market-score"
      style={{ borderColor: color, background: `linear-gradient(90deg, hsla(${read.hue}, 85%, 50%, 0.2), var(--card))` }}
      title="Per index: +1 when price is above its 6-day simple average, +1 when the 6-day is above the 20-day"
    >
      <div className="market-score-num" style={{ color }}>
        Market score {read.score}/{read.max}
      </div>
      <div className="market-score-copy">
        <div className="market-score-msg">{read.message}</div>
        <div className="market-score-breakdown small">{marketScoreBreakdown(trend.indexes)}</div>
      </div>
    </section>
  );
}
