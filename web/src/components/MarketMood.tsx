import { fmtPct, type IssueCounts, type Trend } from "../api";
import { declinersPerAdvancer, maChip, marketScoreRead, ragnarFor, trendLabel } from "../market";

export interface DayChange {
  symbol: string;
  change_pct: number;
}

/**
 * The one State of the Market card: Ragnar (picked by the hidden 0–9 market score), the 6/20/50-day trend call and its
 * detail, the funny line for the score (in the trend label's color), then QQQ / SPY / IWM with today's move and their 6/20/50 chips. No score number.
 */
export function MarketMood({ trend, days, issues }: { trend: Trend; days: DayChange[]; issues?: IssueCounts }) {
  const { label, detail } = trendLabel(trend.call);
  const read = marketScoreRead(trend.score);
  const ragnar = ragnarFor(trend.score);
  const bySymbol = new Map(days.map((d) => [d.symbol, d.change_pct]));
  const changes = trend.indexes.map((index) => bySymbol.get(index.symbol)).filter((v): v is number => v !== undefined);
  const allDown = changes.length === trend.indexes.length && changes.every((v) => v < 0);
  const ratio = issues ? declinersPerAdvancer(issues.advancing, issues.declining) : null;
  const lopsided = ratio !== null && ratio >= 2;

  return (
    <section className={`card trend-banner market-mood ${trend.call}${allDown ? " smash" : ""}`} data-score={read.score}>
      <div className="mood-top">
        <img className="trend-ragnar mood-ragnar" src={ragnar.src} alt={ragnar.alt} title={ragnar.alt} width={112} height={112} />
        <div className="trend-copy">
          <div className="trend-label">{label}</div>
          <p className="trend-detail">
            {detail}
            {lopsided && ratio !== null && <> Universe decliners were {ratio.toFixed(1)} to 1.</>}
          </p>
          <div className="market-score-msg">{read.message}</div>
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
                {index.averages.map((avg) => {
                  const chip = maChip(avg);
                  return (
                    <span key={avg.period} className={`trend-ma ${chip.className}`} title={chip.title}>
                      {avg.period}
                    </span>
                  );
                })}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
