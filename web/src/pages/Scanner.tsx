import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, fmtMoney, fmtPct, type AppConfig, type ScanRow } from "../api";
import { Legend, ScorePill, TfBadges } from "../components/Badges";

type SortKey = "score" | "symbol" | "price" | "change_pct" | "trigger_distance_pct" | "avg_dollar_volume" | "sector";
type Continuity = "any" | "mw" | "full";
type SetupFilter = "any" | "pending" | "inside" | "hammer";

function usePersisted<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    const raw = localStorage.getItem(`strat:${key}`);
    return raw === null ? initial : (JSON.parse(raw) as T);
  });
  useEffect(() => localStorage.setItem(`strat:${key}`, JSON.stringify(value)), [key, value]);
  return [value, setValue] as const;
}

export default function Scanner({ version }: { version: string | null }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const sector = params.get("sector") ?? "";

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [rows, setRows] = useState<ScanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [minPrice, setMinPrice] = usePersisted<number | null>("minPrice", null);
  const [minDvM, setMinDvM] = usePersisted<number | null>("minDvM", null);
  const [continuity, setContinuity] = usePersisted<Continuity>("continuity", "mw");
  const [setupFilter, setSetupFilter] = usePersisted<SetupFilter>("setup", "any");
  const [maxDist, setMaxDist] = usePersisted<number | null>("maxDist", null);
  const [kind, setKind] = usePersisted<"all" | "stock" | "etf">("kind", "all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "score", dir: -1 });

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined);
  }, []);

  const effPrice = minPrice ?? config?.min_price ?? 10;
  const effDv = (minDvM ?? (config ? config.min_dollar_volume / 1e6 : 50)) * 1e6;

  useEffect(() => {
    if (!config) return;
    setLoading(true);
    api
      .scan(effPrice, effDv)
      .then((r) => {
        setRows(r.rows);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [config, effPrice, effDv, version]);

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    const out = rows.filter((r) => {
      if (q && !r.symbol.includes(q) && !r.name.toUpperCase().includes(q)) return false;
      if (sector && r.sector !== sector) return false;
      if (kind !== "all" && r.kind !== kind) return false;
      if (continuity === "mw" && !r.mw_green) return false;
      if (continuity === "full" && !r.full_continuity) return false;
      if (setupFilter === "pending" && (r.trigger === null || r.triggered)) return false;
      if (setupFilter === "inside" && !(["M", "W", "D"] as const).some((t) => r.tf[t]?.inside)) return false;
      if (setupFilter === "hammer" && !(["M", "W", "D"] as const).some((t) => r.tf[t]?.hammer)) return false;
      if (maxDist !== null && (r.trigger_distance_pct === null || r.trigger_distance_pct > maxDist)) return false;
      return true;
    });
    const { key, dir } = sort;
    // Distance sorts by closeness to the trigger, whichever side of it price is on.
    const value = (r: ScanRow) =>
      key === "trigger_distance_pct" && r.trigger_distance_pct !== null ? Math.abs(r.trigger_distance_pct) : r[key];
    out.sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir;
      return ((av as number) - (bv as number)) * dir;
    });
    return out;
  }, [rows, query, sector, kind, continuity, setupFilter, maxDist, sort]);

  const stats = useMemo(
    () => ({
      full: rows.filter((r) => r.full_continuity).length,
      mw: rows.filter((r) => r.mw_green).length,
      pending: rows.filter((r) => r.mw_green && r.trigger !== null && !r.triggered).length,
    }),
    [rows],
  );

  const header = (key: SortKey, label: string, cls = "") => (
    <th
      className={`sortable ${cls} ${sort.key === key ? "active" : ""}`}
      onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : key === "symbol" || key === "sector" || key === "trigger_distance_pct" ? 1 : -1 }))}
    >
      {label}
      {sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </th>
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
          <h1>Long Strat setups</h1>
          <p className="muted">
            S&amp;P 500 + Nasdaq-100 + sector ETFs, ranked by actionability: timeframe continuity, higher-timeframe
            inside bars &amp; hammers, distance to trigger and liquidity.
          </p>
        </div>
        <div className="stat-cards">
          <div className="stat-card">
            <span className="stat-value">{rows.length}</span>
            <span className="stat-label">liquid names</span>
          </div>
          <div className="stat-card">
            <span className="stat-value green-text">{stats.mw}</span>
            <span className="stat-label">M + W green</span>
          </div>
          <div className="stat-card">
            <span className="stat-value green-text">{stats.full}</span>
            <span className="stat-label">full M/W/D continuity</span>
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
            <option value="full">M + W + D green</option>
            <option value="any">Any</option>
          </select>
        </label>
        <label>
          Setup
          <select className="input" value={setupFilter} onChange={(e) => setSetupFilter(e.target.value as SetupFilter)}>
            <option value="any">Any</option>
            <option value="pending">Awaiting trigger</option>
            <option value="inside">Inside bar (M/W/D)</option>
            <option value="hammer">Hammer (M/W/D)</option>
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
        <label>
          Min avg $vol (M)
          <input className="input num" type="number" min={0} step={10} value={effDv / 1e6} onChange={(e) => setMinDvM(e.target.value === "" ? null : Number(e.target.value))} />
        </label>
        <label>
          Max trigger dist %
          <input className="input num" type="number" min={0} step={0.5} placeholder="any" value={maxDist ?? ""} onChange={(e) => setMaxDist(e.target.value === "" ? null : Number(e.target.value))} />
        </label>
      </section>

      <div className="table-meta">
        <span className="muted">
          {loading ? "Loading…" : `${filtered.length} of ${rows.length} shown`}
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
        <div className="card empty-state">No cached data yet. The first download starts automatically; it takes a minute or two.</div>
      )}

      <div className="card table-card">
        <table className="scan-table">
          <thead>
            <tr>
              <th className="rank">#</th>
              {header("symbol", "Symbol")}
              {header("sector", "Sector")}
              {header("price", "Price", "num")}
              {header("change_pct", "Day", "num")}
              <th>M · W · D</th>
              <th>Best setup</th>
              <th className="num">Trigger</th>
              <th className="num">Stop</th>
              {header("trigger_distance_pct", "To trigger", "num")}
              {header("avg_dollar_volume", "Avg $vol", "num")}
              {header("score", "Score", "num")}
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => (
              <tr key={r.symbol} onClick={() => navigate(`/stock/${r.symbol}`)}>
                <td className="rank muted">{i + 1}</td>
                <td>
                  <div className="sym">
                    {r.symbol}
                    {r.kind === "etf" && <span className="etf-chip">ETF</span>}
                  </div>
                  <div className="sub muted">{r.name}</div>
                </td>
                <td className="muted small">
                  <span className="sector-link" onClick={(e) => { e.stopPropagation(); setSector(r.sector); }}>
                    {r.sector}
                  </span>
                </td>
                <td className="num">{r.price.toFixed(2)}</td>
                <td className={`num ${r.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(r.change_pct, 2)}</td>
                <td>
                  <TfBadges tf={r.tf} />
                </td>
                <td className="setup-cell">
                  {r.setup ? (
                    <>
                      <div className={r.triggered ? "setup triggered" : "setup"}>
                        {r.setup}
                        {r.triggered && <span className="trig-chip">triggered</span>}
                      </div>
                      <div className="sub muted reason" title={r.reason}>{r.reason}</div>
                    </>
                  ) : (
                    <span className="sub muted reason" title={r.reason}>{r.reason}</span>
                  )}
                </td>
                <td className="num accent-text">{r.trigger?.toFixed(2) ?? "—"}</td>
                <td className="num red-text">{r.stop?.toFixed(2) ?? "—"}</td>
                <td className="num">{fmtPct(r.trigger_distance_pct)}</td>
                <td className="num muted">{fmtMoney(r.avg_dollar_volume)}</td>
                <td className="num">
                  <ScorePill score={r.score} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
