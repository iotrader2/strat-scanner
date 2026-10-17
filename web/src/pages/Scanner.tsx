import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type AppConfig, type ScanRow } from "../api";
import { Legend } from "../components/Badges";
import { ScanTable } from "../components/ScanTable";
import { Dropdown, type DropdownOption } from "../components/Dropdown";
import { LogSlider } from "../components/LogSlider";
import { fmtCompact, fmtPrice, passesLiquidity } from "../logScale";
import { readPersisted, usePersisted } from "../persist";
import { SkeletonTable } from "../components/Loading";
import {
  leadershipUsesMinRs,
  matchesLeadership,
  MIN_RS_RANGE,
  migrateLeadership,
  sliderToRs,
  type LeadershipFilter,
} from "../leadership";

/** Widest Min RS the Leaders / Weekly setups views allow — hero chips use this, not the current slider. */
const CHIP_RS = sliderToRs(MIN_RS_RANGE.min);
import { RsSlider } from "../components/RsSlider";
import { matchesSetup, type SetupFilter } from "../setupFilter";
import { matchesTheme, themeName, themeOptions } from "../themes";

const PRICE_RANGE = { min: 1, max: 1_000 };
const DOLLAR_VOL_RANGE = { min: 10_000_000, max: 5_000_000_000 };
type Continuity = "any" | "mw" | "full" | "m2u";
type Kind = "all" | "stock" | "etf";

const LEADERSHIP_OPTIONS: DropdownOption<LeadershipFilter>[] = [
  { value: "leaders", label: "Leaders", hint: "Relative strength at or above the Min RS slider, trend not broken." },
  {
    value: "setups_pending",
    label: "Weekly setups · awaiting trigger",
    hint:
      "Leaders (Min RS slider, trend not broken) with a long-side weekly Strat setup that has not broken its trigger yet: inside week, 2-1-2 / 3-1-2 in progress, or a hammer still below its high. Shows the trigger (weekly high) and distance to it. Sorted by score.",
  },
  {
    value: "setups_triggered",
    label: "Weekly setups · triggered",
    hint:
      "Leaders (Min RS slider, trend not broken) whose weekly Strat setup has already broken the trigger: 2-1-2 / 3-1-2 / 1-2-2 / 2D-2U triggered, or a hammer that cleared its high. Sorted by score.",
  },
  {
    value: "breakouts",
    label: "Recent breakouts",
    hint: "Tight-base weekly breakout (volume surge) in the last 3 weekly candles, RS at P50 or better. Ignores the Min RS slider.",
  },
  {
    value: "broken",
    label: "Broken leaders",
    hint: "Trend lost: below the 50-day average or 25%+ below the 6-month high. Same “· broken” flag as the RS chip. Ignores the Min RS slider — dig in with price, theme and the other filters.",
  },
  { value: "all", label: "All names" },
];

type HeroChipKey = "all" | "leaders" | "setupsPending" | "setupsTriggered" | "breakouts" | "broken";
const HERO_CHIPS: { key: HeroChipKey; filter: LeadershipFilter; label: string; tone: "muted" | "green" | "red" }[] = [
  { key: "all", filter: "all", label: "all names", tone: "muted" },
  { key: "leaders", filter: "leaders", label: "leaders", tone: "green" },
  { key: "setupsPending", filter: "setups_pending", label: "awaiting trigger", tone: "green" },
  { key: "setupsTriggered", filter: "setups_triggered", label: "triggered setups", tone: "green" },
  { key: "breakouts", filter: "breakouts", label: "recent breakouts", tone: "green" },
  { key: "broken", filter: "broken", label: "broken leaders", tone: "red" },
];
const CONTINUITY_OPTIONS: DropdownOption<Continuity>[] = [
  { value: "any", label: "Any" },
  { value: "mw", label: "M + W green" },
  { value: "m2u", label: "Monthly 2U" },
  { value: "full", label: "M + W + D green" },
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
  // Continuity was a default gate (M+W green) when the scanner ranked setups; it is a timing option now, so it has a new key.
  const [continuity, setContinuity] = usePersisted<Continuity>("continuityFilter", "any");
  const [savedLeadership] = useState(() => migrateLeadership(readPersisted<string | null>("leadership", null)));
  const [leadership, setLeadership] = usePersisted<LeadershipFilter>("leadership", savedLeadership.filter);
  const [minRsSlider, setMinRs] = usePersisted<number | null>("minRs", null);
  const minRsPct = minRsSlider ?? savedLeadership.minRs ?? MIN_RS_RANGE.default;
  const minRs = sliderToRs(minRsPct);
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
      if (!matchesLeadership(r, leadership, minRs)) return false;
      if (!matchesTheme(r, theme)) return false;
      if (kind !== "all" && r.kind !== kind) return false;
      if (continuity === "mw" && !r.mw_green) return false;
      if (continuity === "full" && !r.full_continuity) return false;
      if (continuity === "m2u" && !r.monthly_2u) return false;
      return matchesSetup(r, setupFilter);
    });
    return out;
  }, [liquid, query, theme, kind, continuity, setupFilter, leadership, minRs]);

  /**
   * Hero chips: full-universe totals for each Leadership category. Never apply the current dropdown, Min RS slider,
   * liquidity, theme or setup filters. Leaders / Weekly setups use the widest Min RS (P50); dig in with the slider.
   */
  const stats = useMemo(
    () => ({
      all: rows.length,
      leaders: rows.filter((r) => matchesLeadership(r, "leaders", CHIP_RS)).length,
      setupsPending: rows.filter((r) => matchesLeadership(r, "setups_pending", CHIP_RS)).length,
      setupsTriggered: rows.filter((r) => matchesLeadership(r, "setups_triggered", CHIP_RS)).length,
      breakouts: rows.filter((r) => matchesLeadership(r, "breakouts")).length,
      broken: rows.filter((r) => matchesLeadership(r, "broken")).length,
    }),
    [rows],
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
            Market leaders first (S&amp;P 500 + Nasdaq-100 + theme additions + sector ETFs): 1M/3M/6M relative strength versus the
            universe and QQQ, theme strength and trend quality. Weekly Strat setups are a timing bonus, not a gate, and names that are
            losing their trend are demoted.
          </p>
        </div>
        <div className="stat-cards" role="group" aria-label="Leadership totals">
          {HERO_CHIPS.map((chip) => {
            const active = leadership === chip.filter;
            return (
              <button
                key={chip.key}
                type="button"
                className={`stat-card stat-card-btn${active ? " active" : ""}`}
                aria-pressed={active}
                onClick={() => setLeadership(chip.filter)}
              >
                <span
                  className={`stat-value ${
                    chip.tone === "red" ? "red-text" : chip.tone === "green" ? "green-text" : ""
                  }`}
                >
                  {stats[chip.key]}
                </span>
                <span className="stat-label">{chip.label}</span>
              </button>
            );
          })}
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
        <Dropdown label="Leadership" header="Filter by relative strength" value={leadership} options={LEADERSHIP_OPTIONS} onChange={setLeadership} />
        <Dropdown
          label="Continuity"
          header="Filter by continuity"
          value={continuity}
          options={CONTINUITY_OPTIONS}
          onChange={setContinuity}
        />
        <Dropdown label="Setup" header="Filter by weekly setup" value={setupFilter} options={SETUP_OPTIONS} onChange={setSetupFilter} />
        <Dropdown label="Type" header="Filter by type" value={kind} options={KIND_OPTIONS} onChange={setKind} />
        {leadershipUsesMinRs(leadership) && (
          <RsSlider value={minRsPct} min={MIN_RS_RANGE.min} max={MIN_RS_RANGE.max} onChange={setMinRs} />
        )}
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
          {!loading && `${filtered.length} of ${rows.length} names shown`}
          {theme && (
            <button className="chip" onClick={() => setTheme("")}>
              {themeName(config?.themes ?? [], theme)} ✕
            </button>
          )}
        </span>
        <Legend />
      </div>
      {error && <div className="banner error">{error}</div>}
      {!loading && filtered.length === 0 && !error && (
        <div className="card empty-state">Nothing matches these filters (if the cache is empty, the first download starts automatically and takes a minute or two).</div>
      )}

      {loading && rows.length === 0 ? (
        <SkeletonTable rows={10} cols={16} label="Scanning for leaders…" />
      ) : (
        <ScanTable rows={filtered} onTheme={setTheme} minRs={minRs} />
      )}
    </div>
  );
}
