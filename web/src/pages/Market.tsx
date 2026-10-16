import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type SectorEtf, type Tf } from "../api";
import { isTimeframe, usePersisted } from "../persist";
import { Legend } from "../components/Badges";
import { CARD_BARS, EtfCard, TfToggle } from "../components/EtfCard";
import { marketRead } from "../market";
import { SkeletonCards } from "../components/Loading";

export default function Market({ version }: { version: string | null }) {
  const [storedTf, setTf] = usePersisted<Tf>("marketTf", "W");
  const tf: Tf = isTimeframe(storedTf) ? storedTf : "W";
  const [etfs, setEtfs] = useState<SectorEtf[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .market(tf, CARD_BARS[tf])
      .then((r) => {
        setEtfs(r.etfs);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [tf, version]);

  const read = marketRead(etfs.map((e) => e.row));

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>State of the Market</h1>
          <p className="muted">
            The Nasdaq-100 (QQQ), S&amp;P 500 (SPY) and Russell 2000 (IWM) with their M/W/D Strat badges, continuity and
            weekly setups. Start here, then drill into <Link className="sector-link" to="/sectors">Sectors</Link> and
            the <Link className="sector-link" to="/">Stock Scanner</Link>.
          </p>
        </div>
        <TfToggle tf={tf} onChange={setTf} />
      </section>

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
      <Legend />

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
