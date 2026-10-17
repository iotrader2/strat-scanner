import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type AppConfig, type ScanRow } from "../api";
import { Legend } from "../components/Badges";
import { ScanTable } from "../components/ScanTable";
import { Dropdown, type DropdownOption } from "../components/Dropdown";
import { LogSlider } from "../components/LogSlider";
import { fmtCompact, fmtPrice, passesLiquidity } from "../logScale";
import { usePersisted } from "../persist";
import { SkeletonTable } from "../components/Loading";
import { matchesSetup, type SetupFilter } from "../setupFilter";
import { matchesTheme, themeName, themeOptions } from "../themes";

const PRICE_RANGE = { min: 1, max: 1_000 };
const DOLLAR_VOL_RANGE = { min: 10_000_000, max: 5_000_000_000 };
type Continuity = "any" | "mw" | "full" | "m2u";
type Kind = "all" | "stock" | "etf";

const CONTINUITY_OPTIONS: DropdownOption<Continuity>[] = [
  { value: "mw", label: "M + W green" },
  { value: "m2u", label: "Monthly 2U" },
  { value: "full", label: "M + W + D green" },
  { value: "any", label: "Any" },
];
const SETUP_OPTIONS: DropdownOption<SetupFilter>[] = [
  { value: "any", label: "Any" },
  { value: "pending", label: "Awaiting trigger" },
  { value: "triggered", label: "Already triggered" },
  { value: "inside", label: "Inside week" },
  { value: "hammer", label: "Weekly hammer" },
];
const KIND_OPTIONS: DropdownOption<Kind>[] = [
  { value: "all", label: "Stocks + ETFs" },
  { value: "stock", label: "Stocks" },
  { value: "etf", label: "ETFs" },
];

export default function Scanner({ version }: { version: string | null }) {
  const [params, setParams] = useSearchParams();
  const theme = params.get("theme") ?? "";

  const [config, setConfig] = useState<AppConfig | null>(null);
  const [rows, setRows] = useState<ScanRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [minPrice, setMinPrice] = usePersisted<number | null>("minPrice", null);
  const [minDvM, setMinDvM] = usePersisted<number | null>("minDvM", null);
  const [continuity, setContinuity] = usePersisted<Continuity>("continuity", "mw");
  const [setupFilter, setSetupFilter] = usePersisted<SetupFilter>("setup", "any");
  const [kind, setKind] = usePersisted<Kind>("kind", "all");
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
    () => rows.filter((r) => passesLiquidity(r, { minPrice: effPrice, minDollarVolume: effDv })),
    [rows, effPrice, effDv],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    const out = liquid.filter((r) => {
      if (q && !r.symbol.includes(q) && !r.name.toUpperCase().includes(q)) return false;
      if (!matchesTheme(r, theme)) return false;
      if (kind !== "all" && r.kind !== kind) return false;
      if (continuity === "mw" && !r.mw_green) return false;
      if (continuity === "full" && !r.full_continuity) return false;
      if (continuity === "m2u" && !r.monthly_2u) return false;
      return matchesSetup(r, setupFilter);
    });
    return out;
  }, [liquid, query, theme, kind, continuity, setupFilter]);

  const stats = useMemo(
    () => ({
      m2u: liquid.filter((r) => r.monthly_2u).length,
      mw: liquid.filter((r) => r.mw_green).length,
      pending: liquid.filter((r) => r.mw_green && r.trigger !== null && !r.triggered).length,
    }),
    [liquid],
  );

  const themeChoices = useMemo<DropdownOption<string>[]>(() => themeOptions(config?.themes ?? []), [config]);

  const setTheme = (t: string) => {
    const next = new URLSearchParams(params);
    if (t) next.set("theme", t);
    else next.delete("theme");
    setParams(next);
  };

  return (
    <div className="page">
      <section className="hero">
        <div>
          <h1>Stock Scanner</h1>
          <p className="muted">
            Long setups on the weekly chart only (S&amp;P 500 + Nasdaq-100 + theme additions + sector ETFs), ranked by actionability:
            Monthly 2U, M/W/D continuity, distance to the weekly trigger, liquidity, relative momentum and theme strength.
          </p>
        </div>
        <div className="stat-cards">
          <div className="stat-card">
            <span className="stat-value green-text">{liquid.length}</span>
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
        <Dropdown
          label="Theme"
          header="Filter by theme"
          value={theme}
          options={themeChoices}
          onChange={setTheme}
        />
        <Dropdown
          label="Continuity"
          header="Filter by continuity"
          value={continuity}
          options={CONTINUITY_OPTIONS}
          onChange={setContinuity}
        />
        <Dropdown label="Setup" header="Filter by weekly setup" value={setupFilter} options={SETUP_OPTIONS} onChange={setSetupFilter} />
        <Dropdown label="Type" header="Filter by type" value={kind} options={KIND_OPTIONS} onChange={setKind} />
        <LogSlider
          label="Min price"
          value={effPrice}
          min={PRICE_RANGE.min}
          max={PRICE_RANGE.max}
          format={fmtPrice}
          onChange={setMinPrice}
        />
        <LogSlider
          label="Min avg $ volume"
          value={effDv}
          min={DOLLAR_VOL_RANGE.min}
          max={DOLLAR_VOL_RANGE.max}
          format={(v) => `$${fmtCompact(v)}`}
          onChange={(v) => setMinDvM(v / 1e6)}
        />
      </section>

      <div className="table-meta">
        <span className="muted">
          {!loading && `${filtered.length} of ${rows.length} weekly setups shown`}
          {theme && (
            <button className="chip" onClick={() => setTheme("")}>
              {themeName(config?.themes ?? [], theme)} ✕
            </button>
          )}
        </span>
        <Legend />
      </div>
      {error && <div className="banner error">{error}</div>}
      {!loading && rows.length === 0 && !error && (
        <div className="card empty-state">No weekly setups match these filters (if the cache is empty, the first download starts automatically and takes a minute or two).</div>
      )}

      {loading && rows.length === 0 ? (
        <SkeletonTable rows={10} cols={16} label="Scanning weekly setups…" />
      ) : (
        <ScanTable rows={filtered} onTheme={setTheme} />
      )}
    </div>
  );
}
