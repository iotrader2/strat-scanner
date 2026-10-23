import { Link } from "react-router-dom";
import { fmtPct, type HigherTf, type MarketEtf, type Tf } from "../api";
import { sessionBadge } from "../market";
import { ScorePill, TfBadges } from "./Badges";
import { TickerLogo } from "./TickerLogo";
import { CandleChart } from "./CandleChart";
import { PerfStrip } from "./PerfStrip";
import { WatchButton } from "./Watch";

/** Index ETF card on State of the Market: candles with H/I markers, M/W/D badges, score and + watch. */
export function EtfCard({
  etf,
  chartHeight = 180,
  visibleBars,
}: {
  etf: MarketEtf;
  chartHeight?: number;
  /** How many of the fetched candles to show. Extra candles warm up the moving averages. */
  visibleBars?: number;
}) {
  const r = etf.row;
  const setup = r.setups?.[0];
  const badge = sessionBadge(etf.session);

  return (
    <div className={`card sector-card ${r.mw_green ? "mw-green" : ""} ${r.change_pct < 0 ? "day-down" : "day-up"}`}>
      <div className="sector-head">
        <div>
          <div className="sym-line">
            <TickerLogo symbol={etf.symbol} size={22} />
            <Link to={`/stock/${etf.symbol}`} className="sym">{etf.symbol}</Link>
            {badge && (
              <span className="session-badge" title={badge.title}>
                {badge.label}
              </span>
            )}
          </div>
          <div className="sub muted">{etf.name}</div>
        </div>
        <div className="sector-right">
          <span className={`day-change ${r.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(r.change_pct, 2)}</span>
          <span className="num muted">{r.price.toFixed(2)}</span>
        </div>
        <WatchButton symbol={etf.symbol} />
      </div>
      <div className="sector-badges">
        <TfBadges tf={r.tf} frames={INDEX_FRAMES} />
        <ScorePill score={r.score} row={r} />
      </div>
      <PerfStrip perf={r.perf} label={`${etf.symbol} price performance`} />
      <CandleChart candles={etf.candles} height={chartHeight} visibleBars={visibleBars} compact />
      <div className="sector-foot">
        <span className="small">
          {setup ? (
            <>
              <b>W</b> {setup.label} · trigger <span className="accent-text">{setup.trigger.toFixed(2)}</span>
            </>
          ) : (
            <span className="muted">No weekly setup</span>
          )}
        </span>
      </div>
    </div>
  );
}

const INDEX_FRAMES: readonly (Tf | HigherTf)[] = ["D", "W", "M", "3M", "6M"];

const CHART_LABEL = { M: "Monthly", W: "Weekly", D: "Daily", "3M": "3M", "6M": "6M" } as const;
export type ChartTf = keyof typeof CHART_LABEL;
const DEFAULT_FRAMES = ["D", "W", "M"] as const satisfies readonly ChartTf[];

export function TfToggle<T extends ChartTf>({
  tf,
  onChange,
  frames,
}: {
  tf: T;
  onChange: (tf: T) => void;
  frames?: readonly T[];
}) {
  const list = frames ?? DEFAULT_FRAMES;
  return (
    <div className="seg">
      {list.map((t) => (
        <button key={t} type="button" className={t === tf ? "active" : ""} onClick={() => onChange(t as T)}>
          {CHART_LABEL[t]}
        </button>
      ))}
    </div>
  );
}

/** Bars to show per timeframe on the compact ETF charts. */
export const CARD_BARS: Record<ChartTf, number> = { M: 30, W: 36, D: 45, "3M": 16, "6M": 12 };
