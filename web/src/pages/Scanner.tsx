import { setupHint, setupLabel } from "../setupDocs";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  focusSetup,
  isSetupFilter,
  leadershipUsesMinRs,
  SETUP_FILTER_KIND,
  matchesLeadership,
  MIN_RS_RANGE,
  migrateLeadership,
  sliderToRs,
  type LeadershipFilter,
} from "../leadership";

/** User-facing name of the filter group. The persisted value stays under the "leadership" key. */
export const SETUPS_FILTER_LABEL = "Setups";

/** Widest Min RS the Leaders / Daily setups views allow — hero chips use this, not the current slider. */
const CHIP_RS = sliderToRs(MIN_RS_RANGE.min);
import { RsSlider } from "../components/RsSlider";
import {
  CANDLE_PATTERNS,
  CANDLE_PATTERN_LABELS,
  isCandlePattern,
  matchesCandlePattern,
  migrateSetupFilter,
  type CandlePattern,
} from "../candlePattern";
import { matchesTheme, themeName, themeOptions } from "../themes";

const PRICE_RANGE = { min: 1, max: 1_000 };
const DOLLAR_VOL_RANGE = { min: 10_000_000, max: 5_000_000_000 };
type Kind = "all" | "stock" | "etf";

export const SETUPS_OPTIONS: DropdownOption<LeadershipFilter>[] = [
  { value: "all", label: "All names", hint: "Every stock and ETF that passes the price / dollar-volume filters, with or without a setup. Ignores the Min RS slider." },
  { value: "leaders", label: "Leaders", hint: "Relative strength at the Min RS cut (default P90) or an RS line versus QQQ that made a 52-week high in the last 5 sessions, trend not broken, score above 70, highest score first. The slider can raise the cut above P90; lowering it does not add other names, and an RS-line high does not bypass a higher cut." },
  {
    value: "laggards",
    label: "Laggards",
    hint: "The mirror of Leaders, for shorts: RS at or below the bottom cut (P10 at the default Min RS P90; widen the slider toward P50 to see more) with a broken trend (below the 50-day average or 25%+ under the 6-month high). No score cut.",
  },
  {
    value: "setup_ep",
    label: "Episodic Pivot",
    hint: "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut; the Leaders score > 70 cut does not apply) with a large gap up today (2%+) on heavy volume (1.5x+ the 20-day average, projected from the session so far). Entry: Opening Range Break above the high of the first 15-min bar. Stop: low of day. Same-day only. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "setup_hvc",
    label: "Delayed High Volume Close",
    hint: "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut; the Leaders score > 70 cut does not apply) with a recent Episodic Pivot gap day (last 10 sessions) whose close price is back above or being retested. Entry: break back through the gap-day close. Stop: low of the entry day. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "setup_flat_base",
    label: "Flat Base Breakout",
    hint: "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut; the Leaders score > 70 cut does not apply) with a tight daily base of 3+ weeks (10% deep at most, ranges shrinking) after a 20%+ prior trend. Entry: above the prior day's high, clearing the base. Stop: prior-day low on a tight breakout candle, else the breakout-day low. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "setup_undercut",
    label: "Undercut and Rally",
    hint: "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut; the Leaders score > 70 cut does not apply) with a close below the ~1-month swing low, reclaimed the next day. Entry: the reclaim of that low. Stop: the undercut low. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "setup_ma_undercut",
    label: "MA Undercut and Rally",
    hint: "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut; the Leaders score > 70 cut does not apply) with a close below the rising 20, 50 or 10-day average, then a strong reclaim (up day closing in the upper half). Entry: through the average. Stop: low of the reclaim day. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "setup_htf",
    label: "High Tight Flag",
    hint: "Leaders (marked leader: P90+ and trend not broken; the Min RS slider can raise the cut; the Leaders score > 70 cut does not apply) with a 50%+ run-up within ~8 weeks, then a 2–5 week flag no more than 10% deep on lighter volume. Entry: break above the flag. Stop: low of the breakout day. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "short_ep",
    label: "Gap-Down Episodic Pivot",
    hint: "Short setup (the scanner's mirror of the long setup; not in the long-only playbook). Laggards (RS at or below the bottom cut: P10 at the default slider, up to P50 as you widen it; trend broken) with a large gap down today (2%+) on heavy volume. Entry: break below the low of the first 15-min bar. Stop: high of day. Same-day only. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "short_hvc",
    label: "Delayed HVC Short",
    hint: "Short setup (the scanner's mirror of the long setup; not in the long-only playbook). Laggards (RS at or below the bottom cut: P10 at the default slider, up to P50 as you widen it; trend broken) with a recent gap-down day (last 10 sessions) whose close price was reclaimed. Entry: break back below the gap-down day's close. Stop: high of the entry day. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "short_flat_base",
    label: "Flat Base Breakdown",
    hint: "Short setup (the scanner's mirror of the long setup; not in the long-only playbook). Laggards (RS at or below the bottom cut: P10 at the default slider, up to P50 as you widen it; trend broken) with a tight daily base of 3+ weeks after a 17%+ decline, ranges shrinking. Entry: below the prior day's low, through the base support. Stop: prior-day high on a tight breakdown candle, else the breakdown-day high. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "short_overcut",
    label: "Overcut and Fail",
    hint: "Short setup (the scanner's mirror of the long setup; not in the long-only playbook). Laggards (RS at or below the bottom cut: P10 at the default slider, up to P50 as you widen it; trend broken) with a close above the ~1-month swing high, then a close back below it the next day. Entry: the failure below that high. Stop: the overcut high. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "short_ma_overcut",
    label: "MA Overcut and Fail",
    hint: "Short setup (the scanner's mirror of the long setup; not in the long-only playbook). Laggards (RS at or below the bottom cut: P10 at the default slider, up to P50 as you widen it; trend broken) with a close above a falling 20, 50 or 10-day average, then a weak rejection back below (down day closing in the lower half). Entry: back below the average. Stop: high of the rejection day. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
  },
  {
    value: "short_ltf",
    label: "Low Tight Flag",
    hint: "Short setup (the scanner's mirror of the long setup; not in the long-only playbook). Laggards (RS at or below the bottom cut: P10 at the default slider, up to P50 as you widen it; trend broken) with a 33%+ drop within ~8 weeks, then a 2–5 week bounce no more than ~11% high on lighter volume. Entry: break below the flag. Stop: high of the breakdown day. Pending and triggered both listed; the row shows this setup's trigger. Sorted by score.",
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
];

const RED_TILES = new Set<LeadershipFilter>([
  "broken", "daily_bearish", "weekly_bearish", "failed_breakouts", "laggards",
  "short_ep", "short_hvc", "short_flat_base", "short_overcut", "short_ma_overcut", "short_ltf",
]);
/** Summary tiles: one per Setups option, in the dropdown's order, labelled like it (lower case). */
export const HERO_CHIPS: { filter: LeadershipFilter; label: string; tone: "muted" | "green" | "red" }[] = SETUPS_OPTIONS.map(
  (o) => ({
    filter: o.value,
    label: o.label.toLowerCase().replace(" trend change", ""),
    tone: o.value === "all" ? "muted" : RED_TILES.has(o.value) ? "red" : "green",
  }),
);
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
export const CANDLE_PATTERN_OPTIONS: DropdownOption<CandlePattern>[] = CANDLE_PATTERNS.map((value) => ({
  value,
  label: CANDLE_PATTERN_LABELS[value],
}));
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
  // Saved under its own key; the old "Setup" filter's Inside week / Weekly hammer carry over once.
  const [storedPattern, setCandlePattern] = usePersisted<CandlePattern>(
    "candlePattern",
    migrateSetupFilter(readPersisted<string | null>("setup", null)),
  );
  const candlePattern: CandlePattern = isCandlePattern(storedPattern) ? storedPattern : "any";
  const [kind, setKind] = usePersisted<Kind>("kind", "all");
  const [savedAtr, setAtrRange] = usePersisted<AtrRange>("atrPct", ATR_PCT_DEFAULT);
  const atrRange = useMemo(() => normalizeAtrRange(savedAtr), [savedAtr]);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.config().then(setConfig).catch(() => undefined);
  }, []);

  // Links from the Setups tab ("Scan long" / "Scan short") open the scanner on that setup: /?setup=setup_htf.
  useEffect(() => {
    const wanted = params.get("setup");
    if (!wanted) return;
    if (isSetupFilter(wanted)) setLeadership(wanted);
    const next = new URLSearchParams(params);
    next.delete("setup");
    setParams(next, { replace: true });
  }, [params, setParams, setLeadership]);

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
      return matchesCandlePattern(r, candlePattern);
    });
    return out.map((r) => focusSetup(r, leadership));
  }, [liquid, query, theme, kind, candlePattern, leadership, minRs, atrRange]);

  /**
   * Hero chips: full-universe totals for each Leadership category. Never apply the current dropdown, Min RS slider,
   * liquidity, theme or setup filters. Leaders and the per-setup tiles use the widest Min RS (P50); dig in with the slider.
   */
  const stats = useMemo(
    () =>
      Object.fromEntries(
        HERO_CHIPS.map((c) => [
          c.filter,
          c.filter === "all" ? rows.length : rows.filter((r) => matchesLeadership(r, c.filter, CHIP_RS)).length,
        ]),
      ) as Record<LeadershipFilter, number>,
    [rows],
  );

  // On phones the tiles are one swipeable row: keep the selected view's tile in sight (e.g. picked from the dropdown).
  const tilesRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = tilesRef.current;
    const tile = el?.querySelector<HTMLElement>(".stat-card-btn.active");
    if (!el || !tile || el.scrollWidth <= el.clientWidth) return;
    const box = el.getBoundingClientRect();
    const t = tile.getBoundingClientRect();
    if (t.left < box.left || t.right > box.right) {
      el.scrollTo({ left: Math.max(0, el.scrollLeft + t.left - box.left - 10), behavior: "smooth" });
    }
  }, [leadership]);

  // Setup names and hover text come from data/setups.yaml (via /api/config) when loaded, so they match the code.
  const setupOptions = useMemo(
    () =>
      SETUPS_OPTIONS.map((o) => ({
        ...o,
        label: setupLabel(o.value, config?.setups) ?? o.label,
        hint: setupHint(o.value, config?.setups) ?? o.hint,
      })),
    [config],
  );
  const tileLabel = (f: LeadershipFilter, fallback: string) =>
    setupLabel(f, config?.setups)?.toLowerCase().replace("moving average", "ma") ?? fallback;

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
        <div className="stat-cards scanner-tiles" role="group" aria-label="Setups totals" ref={tilesRef}>
          {HERO_CHIPS.map((chip) => {
            const active = leadership === chip.filter;
            return (
              <button
                key={chip.filter}
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
                  {stats[chip.filter]}
                </span>
                <span className="stat-label">{tileLabel(chip.filter, chip.label)}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="card filters">
        <div className="filter-row filter-dropdowns">
          <Dropdown label="Type" header="Filter by type" value={kind} options={KIND_OPTIONS} onChange={setKind} />
          <SymbolSearch value={query} onChange={setQuery} />
          <Dropdown
            label="Theme"
            header="Filter by theme"
            value={theme}
            options={themeChoices}
            onChange={setTheme}
          />
          <div className="setups-filter">
            <Dropdown
              label={SETUPS_FILTER_LABEL}
              header="Filter by setup"
              value={leadership}
              options={setupOptions}
              onChange={setLeadership}
            />
            {isSetupFilter(leadership) && (
              <Link className="setup-rules-link small" to={`/setups#${SETUP_FILTER_KIND[leadership]}`}>
                Rules for this setup →
              </Link>
            )}
          </div>
          <Dropdown
            label="Candle Pattern"
            header="Inside bar or hammer on the last completed weekly / daily bar"
            value={candlePattern}
            options={CANDLE_PATTERN_OPTIONS}
            onChange={setCandlePattern}
          />
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
