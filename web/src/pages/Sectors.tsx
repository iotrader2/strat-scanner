import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtPct, type SectorEtf, type Tf } from "../api";
import { isTimeframe, usePersisted } from "../persist";
import { Legend, ScorePill, TfBadges } from "../components/Badges";
import { CandleChart, type PriceLine } from "../components/CandleChart";

const GROUPS: { key: SectorEtf["group"]; title: string }[] = [
  { key: "spdr", title: "SPDR sector ETFs" },
  { key: "industry", title: "Industry ETFs" },
  { key: "benchmark", title: "Benchmarks" },
];

function SectorCard({ etf }: { etf: SectorEtf }) {
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
      </div>
      <div className="sector-badges">
        <TfBadges tf={r.tf} />
        <ScorePill score={r.score} row={r} />
      </div>
      <CandleChart candles={etf.candles} lines={lines} height={180} compact />
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

export default function Sectors({ version }: { version: string | null }) {
  const [storedTf, setTf] = usePersisted<Tf>("sectorsTf", "W");
  const tf: Tf = isTimeframe(storedTf) ? storedTf : "W";
  const [etfs, setEtfs] = useState<SectorEtf[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .sectors(tf, tf === "D" ? 45 : tf === "W" ? 36 : 30)
      .then((r) => setEtfs(r.etfs))
      .finally(() => setLoading(false));
  }, [tf, version]);

  const ranked = useMemo(
    () => [...etfs].sort((a, b) => b.row.score - a.row.score || a.symbol.localeCompare(b.symbol)),
    [etfs],
  );

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Sectors</h1>
          <p className="muted">
            Sector and industry ETFs with their M/W/D Strat badges. Each card lists its weekly setup and trigger;
            green-bordered cards have Monthly and Weekly continuity. Use “Scan sector” to filter the stock scanner.
          </p>
        </div>
        <div className="seg">
          {(["M", "W", "D"] as Tf[]).map((t) => (
            <button key={t} className={t === tf ? "active" : ""} onClick={() => setTf(t)}>
              {t === "M" ? "Monthly" : t === "W" ? "Weekly" : "Daily"}
            </button>
          ))}
        </div>
      </section>

      <div className="card leaderboard">
        <span className="muted small">Strongest → weakest:</span>
        {ranked.filter((e) => e.group !== "benchmark").map((e) => (
          <Link key={e.symbol} to={`/stock/${e.symbol}`} className={`lb-item ${e.row.mw_green ? "green" : "red"}`}>
            {e.symbol} <b>{e.row.score.toFixed(0)}</b>
          </Link>
        ))}
      </div>
      <Legend />

      {loading && etfs.length === 0 && <p className="muted">Loading…</p>}
      {GROUPS.map((g) => {
        const items = ranked.filter((e) => e.group === g.key);
        if (!items.length) return null;
        return (
          <section key={g.key}>
            <h2 className="group-title">{g.title}</h2>
            <div className="sector-grid">
              {items.map((e) => (
                <SectorCard key={e.symbol} etf={e} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
