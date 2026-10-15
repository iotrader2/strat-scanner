import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type AppConfig, type ScanRow } from "../api";
import { Legend } from "../components/Badges";
import { ScanTable } from "../components/ScanTable";
import { LogSlider } from "../components/LogSlider";
import { fmtCompact, passesLiquidity } from "../logScale";
import { usePersisted } from "../persist";

const AVG_VOL_RANGE = { min: 100_000, max: 50_000_000 };
const DOLLAR_VOL_RANGE = { min: 10_000_000, max: 5_000_000_000 };
type Continuity = "any" | "mw" | "full" | "m2u";
type SetupFilter = "any" | "pending" | "inside" | "hammer";

export default function Scanner({ version }: { version: string | null }) {
  const [params, setParams] = useSearchParams();
  const sector = params.get("sector") ?? "";

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [rows, setRows] = useState<ScanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [minPrice, setMinPrice] = usePersisted<number | null>("minPrice", null);
  const [minDvM, setMinDvM] = usePersisted<number | null>("minDvM", null);
  const [minAvgVol, setMinAvgVol] = usePersisted<number>("minAvgVol", AVG_VOL_RANGE.min);
  const [continuity, setContinuity] = usePersisted<Continuity>("continuity", "mw");
  const [setupFilter, setSetupFilter] = usePersisted<SetupFilter>("setup", "any");
  const [kind, setKind] = usePersisted<"all" | "stock" | "etf">("kind", "all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined);
  }, []);

  const effPrice = minPrice ?? config?.min_price ?? 10;
  const effDv = (minDvM ?? (config ? config.min_dollar_volume / 1e6 : 50)) * 1e6;

  useEffect(() => {
    setLoading(true);
    api
      .scan()
      .then((r) => {
        setRows(r.rows);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [version]);

  const liquid = useMemo(
    () => rows.filter((r) => passesLiquidity(r, { minPrice: effPrice, minDollarVolume: effDv, minAvgVolume: minAvgVol })),
    [rows, effPrice, effDv, minAvgVol],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    const out = liquid.filter((r) => {
      if (q && !r.symbol.includes(q) && !r.name.toUpperCase().includes(q)) return false;
      if (sector && r.sector !== sector) return false;
      if (kind !== "all" && r.kind !== kind) return false;
      if (continuity === "mw" && !r.mw_green) return false;
      if (continuity === "full" && !r.full_continuity) return false;
      if (continuity === "m2u" && !r.monthly_2u) return false;
      if (setupFilter === "pending" && (r.trigger === null || r.triggered)) return false;
      if (setupFilter === "inside" && !r.tf.W?.inside) return false;
      if (setupFilter === "hammer" && !r.tf.W?.hammer) return false;
      return true;
    });
    return out;
  }, [liquid, query, sector, kind, continuity, setupFilter]);

  const stats = useMemo(
    () => ({
      m2u: liquid.filter((r) => r.monthly_2u).length,
      mw: liquid.filter((r) => r.mw_green).length,
      pending: liquid.filter((r) => r.mw_green && r.trigger !== null && !r.triggered).length,
    }),
    [liquid],
  );

  const setSector = (s: string) => {
    const next = new URLSearchParams(params);
    if (s) next.set("sector", s);
    else next.delete("sector");
    setParams(next);
  };

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Weekly Strat setups</h1>
          <p className="muted">
            Long setups on the weekly chart only (S&amp;P 500 + Nasdaq-100 + sector ETFs), ranked by actionability:
            Monthly 2U, M/W/D continuity, distance to the weekly trigger and liquidity.
          </p>
        </div>
        <div className="stat-cards">
          <div className="stat-card">
            <span className="stat-value">{liquid.length}</span>
            <span className="stat-label">weekly setups</span>
          </div>
          <div className="stat-card">
            <span className="stat-value green-text">{stats.mw}</span>
            <span className="stat-label">M + W green</span>
          </div>
          <div className="stat-card">
            <span className="stat-value green-text">{stats.m2u}</span>
            <span className="stat-label">Monthly 2U</span>
          </div>
          <div className="stat-card">
            <span className="stat-value accent-text">{stats.pending}</span>
            <span className="stat-label">M+W green, awaiting trigger</span>
          </div>
        </div>
      </section>

      <section className="card filters">
        <input className="input search" placeholder="Search symbol or name…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <label>
          Sector
          <select className="input" value={sector} onChange={(e) => setSector(e.target.value)}>
            <option value="">All sectors</option>
            {config?.sectors.map((s) => (
              <option key={s} value={s}>
                {s} ({config.sector_etfs[s]})
              </option>
            ))}
            <option value="Benchmark">Benchmark ETFs</option>
          </select>
        </label>
        <label>
          Continuity
          <select className="input" value={continuity} onChange={(e) => setContinuity(e.target.value as Continuity)}>
            <option value="mw">M + W green</option>
            <option value="m2u">Monthly 2U</option>
            <option value="full">M + W + D green</option>
            <option value="any">Any</option>
          </select>
        </label>
        <label>
          Setup
          <select className="input" value={setupFilter} onChange={(e) => setSetupFilter(e.target.value as SetupFilter)}>
            <option value="any">Any</option>
            <option value="pending">Awaiting trigger</option>
            <option value="inside">Inside week</option>
            <option value="hammer">Weekly hammer</option>
          </select>
        </label>
        <label>
          Type
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as "all" | "stock" | "etf")}>
            <option value="all">Stocks + ETFs</option>
            <option value="stock">Stocks</option>
            <option value="etf">ETFs</option>
          </select>
        </label>
        <label>
          Min price $
          <input className="input num" type="number" min={0} value={effPrice} onChange={(e) => setMinPrice(e.target.value === "" ? null : Number(e.target.value))} />
        </label>
        <LogSlider
          label="Min avg $ volume"
          value={effDv}
          min={DOLLAR_VOL_RANGE.min}
          max={DOLLAR_VOL_RANGE.max}
          format={(v) => `$${fmtCompact(v)}`}
          onChange={(v) => setMinDvM(v / 1e6)}
        />
        <LogSlider
          label="Min avg volume (shares)"
          value={minAvgVol}
          min={AVG_VOL_RANGE.min}
          max={AVG_VOL_RANGE.max}
          format={fmtCompact}
          onChange={setMinAvgVol}
        />
      </section>

      <div className="table-meta">
        <span className="muted">
          {loading ? "Loading…" : `${filtered.length} of ${rows.length} weekly setups shown`}
          {sector && (
            <button className="chip" onClick={() => setSector("")}>
              {sector} ✕
            </button>
          )}
        </span>
        <Legend />
      </div>
      {error && <div className="banner error">{error}</div>}
      {!loading && rows.length === 0 && !error && (
        <div className="card empty-state">No weekly setups match these filters (if the cache is empty, the first download starts automatically and takes a minute or two).</div>
      )}

      <ScanTable rows={filtered} onSector={setSector} />
    </div>
  );
}
