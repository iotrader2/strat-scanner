import { useMemo } from "react";
import { Link } from "react-router-dom";
import { fmtPct, type SectorEtf } from "../api";
import { ScorePill, TfBadges } from "./Badges";
import { CandleChart, type PriceLine } from "./CandleChart";
import { WatchButton } from "./Watch";

/** ETF card used on Sectors and State of the Market: candles with H/I markers, M/W/D badges, score and + watch. */
export function EtfCard({ etf, chartHeight = 180 }: { etf: SectorEtf; chartHeight?: number }) {
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
        {etf.group !== "benchmark" && (
          <Link className="chip" to={`/?sector=${encodeURIComponent(etf.sector)}`}>
            Scan {etf.sector.replace("Information Technology", "Tech")} →
          </Link>
        )}
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
