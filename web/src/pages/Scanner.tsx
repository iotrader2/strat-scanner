import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, fmtPct, type AppConfig, type ScanRow } from "../api";
import { ScanTable, type ExtraColumn } from "../components/ScanTable";
import { Dropdown, type DropdownOption } from "../components/Dropdown";
import { AtrSlider } from "../components/AtrSlider";
import { LogSlider } from "../components/LogSlider";
import { ATR_PCT_DEFAULT, normalizeAtrRange, passesAtr, type AtrRange } from "../atrFilter";
import { fmtCompact, fmtPrice, passesLiquidity } from "../logScale";
import { clearRetiredFilters, readPersisted, usePersisted } from "../persist";
import { SkeletonTable } from "../components/Loading";
import { SymbolSearch } from "../components/SymbolSearch";
import { matchesSymbol } from "../symbolSearch";
import { keepIndexEtf } from "../indexEtfs";
import {
  detailTfFor,
  leadershipUsesMinRs,
  matchesLeadership,
  MIN_RS_RANGE,
  migrateLeadership,
  sliderToRs,
  type LeadershipFilter,
} from "../leadership";

/** User-facing name of the filter group. The persisted value stays under the "leadership" key. */
export const SETUPS_FILTER_LABEL = "Setups";

/** Widest Min RS the Leaders / Weekly setups views allow — hero chips use this, not the current slider. */
const CHIP_RS = sliderToRs(MIN_RS_RANGE.min);
import { RsSlider } from "../components/RsSlider";
import { matchesSetup, type SetupFilter } from "../setupFilter";
import { matchesTheme, themeName, themeOptions } from "../themes";

const PRICE_RANGE = { min: 1, max: 1_000 };
const DOLLAR_VOL_RANGE = { min: 10_000_000, max: 5_000_000_000 };
type Kind = "all" | "stock" | "etf";

export const SETUPS_OPTIONS: DropdownOption<LeadershipFilter>[] = [
  { value: "leaders", label: "Leaders", hint: "Only names marked leader (relative strength P90 or better, trend not broken), highest score first. The Min RS slider can raise the cut above P90; it never adds non-leaders." },
  {
    value: "setups_pending",
    label: "Weekly strat awaiting trigger",
    hint:
      "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut) with a long-side weekly Strat setup on the last completed week — not the week still in progress — that has not broken its trigger yet: inside week, 2-1-2 / 3-1-2 in progress, or a hammer still below its high. Shows the trigger (that week's high) and distance to it. Sorted by score.",
  },
  {
    value: "setups_triggered",
    label: "Weekly strat already triggered",
    hint:
      "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut) whose last completed weekly Strat setup has already broken the trigger: 2-1-2 / 3-1-2 / 1-2-2 / 2D-2U triggered, or a hammer that cleared its high. The week still in progress does not count. Sorted by score.",
  },
  {
    value: "daily_bullish",
    label: "Daily bullish trend change",
    hint:
      "Daily MACD (6,20,9) histogram turned up on the most recent daily bar (the first green bar, at or above zero, after 3 or more red bars; same math as the green chart arrow), with the latest close above the 50-day SMA. Names without a 50-day SMA are left out. Today's bar counts while the session is still open, the same way the daily Strat badge does. Ignores the Min RS slider.",
  },
  {
    value: "daily_bearish",
    label: "Daily bearish trend change",
    hint:
      "Daily MACD (6,20,9) histogram turned down on the most recent daily bar (the first red bar, below zero, after 3 or more green bars; same math as the red chart arrow), with the latest close below the 50-day SMA. Names without a 50-day SMA are left out. Today's bar counts while the session is still open, the same way the daily Strat badge does. Ignores the Min RS slider.",
  },
  {
    value: "weekly_bullish",
    label: "Weekly bullish trend change",
    hint:
      "Weekly MACD (6,20,9) histogram turned up on the current weekly bar (the first green bar, at or above zero, after 3 or more red bars; same math as the green arrow on the weekly chart), with the latest close above the 10-week SMA. This week's bar counts while the week is still open, the same way the daily trend change uses today's bar. Names with fewer than 10 weeks are left out. Ignores the Min RS slider.",
  },
  {
    value: "weekly_bearish",
    label: "Weekly bearish trend change",
    hint:
      "Weekly MACD (6,20,9) histogram turned down on the current weekly bar (the first red bar, below zero, after 3 or more green bars; same math as the red arrow on the weekly chart), with the latest close below the 10-week SMA. This week's bar counts while the week is still open, the same way the daily trend change uses today's bar. Names with fewer than 10 weeks are left out. Ignores the Min RS slider.",
  },
  {
    value: "breakouts",
    label: "Recent breakouts",
    hint: "Tight-base weekly breakout (volume surge) in the last 3 weekly candles, RS at P50 or better. Ignores the Min RS slider.",
  },
  {
    value: "failed_breakouts",
    label: "Failed breakouts",
    hint: "The opposite of Recent breakouts: a high-volume weekly close above a tight base in the last 8 weeks (same detection) that price has since closed back below. Shows the breakout date, the breakout level (the base high) and how far price is below it, most recent failure first. RS at P50 or better, any trend; ignores the Min RS slider. A warning, not a buy signal.",
  },
  {
    value: "broken",
    label: "Broken leaders",
    hint: "Trend lost: below the 50-day average or 25%+ below the 6-month high. Same “· broken” flag as the RS chip. Ignores the Min RS slider — dig in with price, theme and the other filters.",
  },
  { value: "all", label: "All names" },
];

type HeroChipKey =
  | "all"
  | "leaders"
  | "setupsPending"
  | "setupsTriggered"
  | "dailyBullish"
  | "dailyBearish"
  | "weeklyBullish"
  | "weeklyBearish"
  | "breakouts"
  | "failedBreakouts"
  | "broken";
const HERO_CHIPS: { key: HeroChipKey; filter: LeadershipFilter; label: string; tone: "muted" | "green" | "red" }[] = [
  { key: "all", filter: "all", label: "all names", tone: "muted" },
  { key: "leaders", filter: "leaders", label: "leaders", tone: "green" },
  { key: "setupsPending", filter: "setups_pending", label: "awaiting trigger", tone: "green" },
  { key: "setupsTriggered", filter: "setups_triggered", label: "already triggered", tone: "green" },
  { key: "dailyBullish", filter: "daily_bullish", label: "daily bullish", tone: "green" },
  { key: "dailyBearish", filter: "daily_bearish", label: "daily bearish", tone: "red" },
  { key: "weeklyBullish", filter: "weekly_bullish", label: "weekly bullish", tone: "green" },
  { key: "weeklyBearish", filter: "weekly_bearish", label: "weekly bearish", tone: "red" },
  { key: "breakouts", filter: "breakouts", label: "recent breakouts", tone: "green" },
  { key: "failedBreakouts", filter: "failed_breakouts", label: "failed breakouts", tone: "red" },
  { key: "broken", filter: "broken", label: "broken leaders", tone: "red" },
];
/** Columns of the Failed breakouts view: when it broke out, the level, how far price is below it and when it failed. */
const FAILED_COLUMNS: ExtraColumn[] = [
  {
    key: "failed_week",
    label: "Broke out",
    className: "muted small",
    sortValue: (r) => r.failed_breakout?.week ?? null,
    render: (r) => r.failed_breakout?.week ?? "—",
  },
  {
    key: "failed_level",
    label: "Level",
    className: "num",
    sortValue: (r) => r.failed_breakout?.level ?? null,
    render: (r) => r.failed_breakout?.level.toFixed(2) ?? "—",
  },
  {
    key: "failed_below",
    label: "Below level",
    className: "num",
    ascendingFirst: true,
    sortValue: (r) => r.failed_breakout?.below_pct ?? null,
    render: (r) =>
      r.failed_breakout ? (
        <span className="red-text" title={`Deepest close since the breakout: ${fmtPct(r.failed_breakout.low_pct)} vs the level`}>
          {fmtPct(r.failed_breakout.below_pct)}
        </span>
      ) : (
        "—"
      ),
  },
  {
    key: "failed_on",
    label: "Failed",
    className: "muted small",
    sortValue: (r) => r.failed_breakout?.failed_on ?? null,
    render: (r) =>
      r.failed_breakout ? (
        <span title={`${r.failed_breakout.sessions_below} session(s) below the level`}>{r.failed_breakout.failed_on}</span>
      ) : (
        "—"
      ),
  },
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
  const [savedLeadership] = useState(() => migrateLeadership(readPersisted<string | null>("leadership", null)));
  const [leadership, setLeadership] = usePersisted<LeadershipFilter>("leadership", savedLeadership.filter);
  const [minRsSlider, setMinRs] = usePersisted<number | null>("minRs", null);
  const minRsPct = minRsSlider ?? savedLeadership.minRs ?? MIN_RS_RANGE.default;
  const minRs = sliderToRs(minRsPct);
  const [setupFilter, setSetupFilter] = usePersisted<SetupFilter>("setup", "any");
  const [kind, setKind] = usePersisted<Kind>("kind", "all");
  const [savedAtr, setAtrRange] = usePersisted<AtrRange>("atrPct", ATR_PCT_DEFAULT);
  const atrRange = useMemo(() => normalizeAtrRange(savedAtr), [savedAtr]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined);
  }, []);

  // Filters that no longer exist (the Continuity dropdown): drop their saved values so nothing reads them again.
  useEffect(() => clearRetiredFilters(), []);

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
    const out = liquid.filter((r) => {
      if (!matchesSymbol(r.symbol, query)) return false;
      // ETFs view: QQQ / SPY / IWM are always listed as reference rows (they are rarely ETF leaders).
      if (!keepIndexEtf(r, kind) && !matchesLeadership(r, leadership, minRs)) return false;
      if (!matchesTheme(r, theme)) return false;
      if (kind !== "all" && r.kind !== kind) return false;
      if (!passesAtr(r, atrRange)) return false;
      return matchesSetup(r, setupFilter);
    });
    return out;
  }, [liquid, query, theme, kind, setupFilter, leadership, minRs, atrRange]);

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
      dailyBullish: rows.filter((r) => matchesLeadership(r, "daily_bullish")).length,
      dailyBearish: rows.filter((r) => matchesLeadership(r, "daily_bearish")).length,
      weeklyBullish: rows.filter((r) => matchesLeadership(r, "weekly_bullish")).length,
      weeklyBearish: rows.filter((r) => matchesLeadership(r, "weekly_bearish")).length,
      breakouts: rows.filter((r) => matchesLeadership(r, "breakouts")).length,
      failedBreakouts: rows.filter((r) => matchesLeadership(r, "failed_breakouts")).length,
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
          <p className="muted">Pick a group, then narrow the list with the filters.</p>
        </div>
        <div className="stat-cards" role="group" aria-label="Setups totals">
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
        <div className="filter-row filter-dropdowns">
          <SymbolSearch value={query} onChange={setQuery} />
          <Dropdown
            label="Theme"
            header="Filter by theme"
            value={theme}
            options={themeChoices}
            onChange={setTheme}
          />
          <Dropdown
            label={SETUPS_FILTER_LABEL}
            header="Filter by setup"
            value={leadership}
            options={SETUPS_OPTIONS}
            onChange={setLeadership}
          />
          <Dropdown label="Setup" header="Filter by weekly setup" value={setupFilter} options={SETUP_OPTIONS} onChange={setSetupFilter} />
          <Dropdown label="Type" header="Filter by type" value={kind} options={KIND_OPTIONS} onChange={setKind} />
        </div>
        <div className="filter-row filter-sliders">
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
          <AtrSlider value={atrRange} onChange={setAtrRange} />
        </div>
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
      </div>
      {error && <div className="banner error">{error}</div>}
      {!loading && filtered.length === 0 && !error && (
        <div className="card empty-state">Nothing matches these filters (if the cache is empty, the first download starts automatically and takes a minute or two).</div>
      )}

      {loading && rows.length === 0 ? (
        <SkeletonTable rows={10} cols={16} label="Scanning for leaders…" />
      ) : leadership === "failed_breakouts" ? (
        <ScanTable
          key="failed"
          rows={filtered}
          pinSymbol={query}
          onTheme={setTheme}
          minRs={minRs}
          extraColumns={FAILED_COLUMNS}
          initialSort={{ key: "failed_on", dir: -1 }}
          detailTf={detailTfFor(leadership)}
        />
      ) : (
        <ScanTable key="default" rows={filtered} pinSymbol={query} onTheme={setTheme} minRs={minRs} detailTf={detailTfFor(leadership)} />
      )}
    </div>
  );
}
