import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Breadth, type HigherTf, type MarketEtf, type Tf, type Trend } from "../api";
import { isTimeframe, usePersisted } from "../persist";
import { CARD_BARS, EtfCard, TfToggle } from "../components/EtfCard";
import { BreadthPanel } from "../components/Breadth";
import { TrendBanner } from "../components/TrendBanner";
import { marketRead } from "../market";
import { SkeletonCards } from "../components/Loading";

type IndexTf = Tf | HigherTf;
const INDEX_CHARTS: readonly IndexTf[] = ["D", "W", "M", "3M", "6M"];

function isIndexTf(v: unknown): v is IndexTf {
  return v === "3M" || v === "6M" || isTimeframe(v);
}

export default function Market({ version }: { version: string | null }) {
  const [storedTf, setTf] = usePersisted<IndexTf>("marketTf", "W");
  const tf: IndexTf = isIndexTf(storedTf) ? storedTf : "W";
  const [etfs, setEtfs] = useState<MarketEtf[]>([]);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [breadth, setBreadth] = useState<Breadth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .market(tf, CARD_BARS[tf])
      .then((r) => {
        setEtfs(r.etfs);
        setTrend(r.trend);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tf, version]);

  useEffect(() => {
    api
      .breadth()
      .then(setBreadth)
      .catch(() => setBreadth(null));
  }, [version]);

  const read = marketRead(etfs.map((e) => e.row));

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>State of the Market</h1>
          <p className="muted">
            How the big indexes are doing. Check them here, then open <Link className="sector-link" to="/themes">Themes</Link> or
            the <Link className="sector-link" to="/">Stock Scanner</Link>.
          </p>
        </div>
      </section>

      {trend && (
        <TrendBanner
          trend={trend}
          days={etfs.map((e) => ({ symbol: e.symbol, change_pct: e.row.change_pct }))}
          nasdaq={breadth?.issues?.nasdaq}
        />
      )}

      {etfs.length > 0 && (
        <div className={`card leaderboard market-read ${read.tone}`}>
          <span className="small">{read.summary}</span>
          {etfs.map((e) => (
            <Link key={e.symbol} to={`/stock/${e.symbol}`} className={`lb-item ${e.row.mw_green ? "green" : "red"}`}>
              {e.symbol} <b>{e.row.score.toFixed(0)}</b>
            </Link>
          ))}
        </div>
      )}
      {breadth && <BreadthPanel breadth={breadth} />}
      <div className="market-tf">
        <TfToggle tf={tf} frames={INDEX_CHARTS} onChange={setTf} />
      </div>

      {error && <div className="banner error">{error}</div>}
      {loading && etfs.length === 0 && (
        <SkeletonCards count={3} chartHeight={300} className="sector-grid market-grid" label="Loading QQQ, SPY and IWM…" />
      )}
      <div className="sector-grid market-grid">
        {etfs.map((e) => (
          <EtfCard key={e.symbol} etf={e} chartHeight={300} />
        ))}
      </div>
    </div>
  );
}
