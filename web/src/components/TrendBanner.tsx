import { fmtPct, type IssueCounts, type Trend } from "../api";
import { declinersPerAdvancer, trendLabel } from "../market";

export interface DayChange {
  symbol: string;
  change_pct: number;
}

/** Bold 10/20/50-day call, with today's index moves at the same size so a bad session is obvious. */
export function TrendBanner({ trend, days, nasdaq }: { trend: Trend; days: DayChange[]; nasdaq?: IssueCounts }) {
  const { label, detail } = trendLabel(trend.call);
  const bySymbol = new Map(days.map((d) => [d.symbol, d.change_pct]));
  const changes = trend.indexes.map((index) => bySymbol.get(index.symbol)).filter((v): v is number => v !== undefined);
  const allDown = changes.length === trend.indexes.length && changes.every((v) => v < 0);
  const ratio = nasdaq ? declinersPerAdvancer(nasdaq.advancing, nasdaq.declining) : null;
  const lopsided = ratio !== null && ratio >= 2;

  return (
    <section className={`card trend-banner ${trend.call}${allDown ? " smash" : ""}`}>
      <div className="trend-lead">
        {trend.call === "off" && (
          <img className="trend-ragnar" src="/ragnar-no-trade.png" alt="Ragnar says no" width={64} height={64} />
        )}
        {trend.call === "on" && (
          <img className="trend-ragnar" src="/ragnar-game-on.png" alt="Ragnar says game on" width={64} height={64} />
        )}
        <div className="trend-copy">
          <div className="trend-label">{label}</div>
          <p className="trend-detail">
            {detail}
            {lopsided && ratio !== null && <> Nasdaq decliners were {ratio.toFixed(1)} to 1.</>}
          </p>
        </div>
      </div>
      <div className="trend-indexes">
        {trend.indexes.map((index) => {
          const change = bySymbol.get(index.symbol);
          const down = change !== undefined && change < 0;
          return (
            <div key={index.symbol} className="trend-index">
              <span className="sym">{index.symbol}</span>
              {change !== undefined && (
                <span className={`trend-day ${down ? "red-text" : "green-text"}`}>{fmtPct(change, 2)}</span>
              )}
              <span className="trend-mas">
                {index.averages.map((avg) => (
                  <span key={avg.period} className={`trend-ma ${avg.above ? "above" : "below"}`} title={`${avg.period}-day average ${avg.value.toFixed(2)}`}>
                    {avg.period}
                  </span>
                ))}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
