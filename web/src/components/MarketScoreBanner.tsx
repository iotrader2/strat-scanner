import type { Trend } from "../api";
import { marketScoreRead } from "../market";

/**
 * One-line market mood at the top of State of the Market. The hidden 0–9 score (QQQ, SPY and IWM, +1 for each 6/20/50-day
 * simple average the price is above) picks the message and the red-to-green color; the 6/20/50 chips on the trend banner
 * show the detail, so no number is printed here.
 */
export function MarketScoreBanner({ trend }: { trend: Pick<Trend, "score"> }) {
  const read = marketScoreRead(trend.score);
  return (
    <section
      className="card market-score"
      data-score={read.score}
      style={{ borderColor: `hsl(${read.hue}, 85%, 55%)`, background: `linear-gradient(90deg, hsla(${read.hue}, 85%, 50%, 0.22), var(--card))` }}
    >
      <div className="market-score-msg">{read.message}</div>
    </section>
  );
}
