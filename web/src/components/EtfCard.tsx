import { useMemo } from "react";
import { Link } from "react-router-dom";
import { fmtPct, type MarketEtf } from "../api";
import { ScorePill, TfBadges } from "./Badges";
import { CandleChart, type PriceLine } from "./CandleChart";
import { PerfStrip } from "./PerfStrip";
import { WatchButton } from "./Watch";

/** Index ETF card on State of the Market: candles with H/I markers, M/W/D badges, score and + watch. */
export function EtfCard({ etf, chartHeight = 180 }: { etf: MarketEtf; chartHeight?: number }) {
  const r = etf.row;
  const lines = useMemo<PriceLine[]>(() => {
    const s = r.setups?.find((x) => !x.triggered) ?? r.setups?.[0];
    return s ? [{ price: s.trigger, color: "#38bdf8", title: "trigger" }] : [];
  }, [r.setups]);
  const setup = r.setups?.[0];

  return (
    <div className={`card sector-card ${r.mw_green ? "mw-green" : ""}`}>
      <div className="sector-head">
        <div>
          <Link to={`/stock/${etf.symbol}`} className="sym">{etf.symbol}</Link>
          <div className="sub muted">{etf.name}</div>
        </div>
        <div className="sector-right">
          <span className="num">{r.price.toFixed(2)}</span>
          <span className={`small ${r.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(r.change_pct, 2)}</span>
        </div>
        <WatchButton symbol={etf.symbol} />
      </div>
      <div className="sector-badges">
        <TfBadges tf={r.tf} />
        <ScorePill score={r.score} row={r} />
      </div>
      <PerfStrip perf={r.perf} label={`${etf.symbol} price performance`} />
      <CandleChart candles={etf.candles} lines={lines} height={chartHeight} compact />
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

const TF_LABEL = { M: "Monthly", W: "Weekly", D: "Daily" } as const;

export function TfToggle({ tf, onChange }: { tf: keyof typeof TF_LABEL; onChange: (tf: keyof typeof TF_LABEL) => void }) {
  return (
    <div className="seg">
      {(["M", "W", "D"] as const).map((t) => (
        <button key={t} className={t === tf ? "active" : ""} onClick={() => onChange(t)}>
          {TF_LABEL[t]}
        </button>
      ))}
    </div>
  );
}

/** Bars to show per timeframe on the compact ETF charts. */
export const CARD_BARS = { M: 30, W: 36, D: 45 } as const;
