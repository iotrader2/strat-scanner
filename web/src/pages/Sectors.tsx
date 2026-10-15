import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type SectorEtf, type Tf } from "../api";
import { isTimeframe, usePersisted } from "../persist";
import { Legend } from "../components/Badges";
import { CARD_BARS, EtfCard, TfToggle } from "../components/EtfCard";

const GROUPS: { key: SectorEtf["group"]; title: string }[] = [
  { key: "spdr", title: "SPDR sector ETFs" },
  { key: "industry", title: "Industry ETFs" },
];

export default function Sectors({ version }: { version: string | null }) {
  const [storedTf, setTf] = usePersisted<Tf>("sectorsTf", "W");
  const tf: Tf = isTimeframe(storedTf) ? storedTf : "W";
  const [etfs, setEtfs] = useState<SectorEtf[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .sectors(tf, CARD_BARS[tf])
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
            green-bordered cards have Monthly and Weekly continuity. Use “Scan sector” to filter the Stock Scanner. The
            index benchmarks are on <Link className="sector-link" to="/market">State of the Market</Link>.
          </p>
        </div>
        <TfToggle tf={tf} onChange={setTf} />
      </section>

      <div className="card leaderboard">
        <span className="muted small">Strongest → weakest:</span>
        {ranked.map((e) => (
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
                <EtfCard key={e.symbol} etf={e} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
