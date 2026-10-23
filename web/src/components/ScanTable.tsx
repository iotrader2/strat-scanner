import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { fmtMoney, fmtPct, type ScanRow, type Tf } from "../api";
import { triggerChip } from "../setupFilter";
import { DETAIL_TF_KEY, writePersisted } from "../persist";
import { fmtPerf, isPerfSort, perfClass, perfSortValue, PERF_PERIODS, type PerfSort } from "../perf";
import {
  breakoutLabel,
  dailyTrendBadge,
  weeklyTrendBadge,
  failedBreakoutLabel,
  LEADER_RS,
  NO_SETUP_LEADER,
  noSetupLabel,
  triggerHint,
} from "../leadership";
import { rsChipView } from "../rsChange";
import { AddedChip, ScorePill, TfBadges } from "./Badges";
import { TickerLogo } from "./TickerLogo";
import { pinExactSymbol } from "../symbolSearch";
import { isIndexEtf } from "../indexEtfs";
import { EarningsIcon } from "./EarningsIcon";
import { WatchButton } from "./Watch";

/** Relative-strength change chip: the change vs a week ago, a flag when the leader is weakening or broken, and a NEW marker for fresh transitions. A name with none of those shows nothing. */
function RsChip({ row }: { row: ScanRow }) {
  const view = rsChipView(row);
  if (!view) return null;
  const parts: ReactNode[] = [];
  if (view.delta) parts.push(<span key="delta" className={`rs-delta ${view.delta.dir}`}>{view.delta.text}</span>);
  if (view.newMarker) {
    parts.push(
      <span key="new">
        <span className={`rs-new ${view.newMarker.kind}`}>NEW</span>
        {` · ${view.newMarker.label}`}
      </span>,
    );
  }
  if (view.flag) parts.push(<span key="flag">{view.flag}</span>);
  if (view.kill) parts.push(<span key="kill" className="rs-kill">{view.kill.replace(/^ · /, "")}</span>);
  if (parts.length === 0) return null;
  return (
    <span className={`rs-chip ${view.level}`}>
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 ? " · " : null}
          {part}
        </span>
      ))}
    </span>
  );
}

/** Trigger and distance cells: the weekly setup's trigger, or (muted) the nearest weekly high for a name with no setup. */
function TriggerCells({ row }: { row: ScanRow }) {
  const hint = triggerHint(row);
  if (!hint) {
    return (
      <>
        <td className="num">—</td>
        <td className="num">—</td>
      </>
    );
  }
  if (hint.nearest) {
    return (
      <>
        <td className="num muted" title={`Nearest trigger: ${hint.label}`}>
          {hint.price.toFixed(2)}
        </td>
        <td className="num muted" title={`Nearest trigger: ${hint.label}`}>
          {fmtPct(hint.distancePct)}
        </td>
      </>
    );
  }
  return (
    <>
      <td className="num accent-text">{hint.price.toFixed(2)}</td>
      <td className="num">{fmtPct(row.trigger_distance_pct)}</td>
    </>
  );
}

/** Day % change cell (the trading lists place it next to Day range via ListTable). */
function DayCell({ row }: { row: ScanRow }) {
  return <td className={`num ${row.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(row.change_pct, 2)}</td>;
}

export type SortKey =
  | "score"
  | "symbol"
  | "price"
  | "change_pct"
  | "trigger_distance_pct"
  | "avg_dollar_volume"
  | "atr"
  | "atr_pct"
  | "theme"
  | PerfSort;

export function sortRows(rows: ScanRow[], key: SortKey, dir: 1 | -1): ScanRow[] {
  // Distance sorts by closeness to the trigger, whichever side of it price is on.
  return sortBy(rows, (r) => {
    if (isPerfSort(key)) return perfSortValue(r, key);
    if (key === "theme") return r.theme_name ?? null;
    return key === "trigger_distance_pct" && r.trigger_distance_pct !== null ? Math.abs(r.trigger_distance_pct) : r[key];
  }, dir);
}

/** Sort by any value; null/undefined values always go last. */
export function sortBy<T>(rows: T[], value: (r: T) => unknown, dir: 1 | -1): T[] {
  return [...rows].sort((a, b) => {
    const av = value(a);
    const bv = value(b);
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir;
    return ((av as number) - (bv as number)) * dir;
  });
}

const ASCENDING_FIRST: SortKey[] = ["symbol", "theme", "trigger_distance_pct"];

/** Extra sortable column (e.g. a position's entry price or P/L). */
export interface ExtraColumn {
  key: string;
  label: string;
  className?: string;
  sortValue: (r: ScanRow) => number | string | null;
  /** Sort ascending on the first click (like Symbol) instead of descending. */
  ascendingFirst?: boolean;
  render: (r: ScanRow) => ReactNode;
}

interface Props {
  rows: ScanRow[];
  /** Makes the Theme cell a link that filters by that theme id. */
  onTheme?: (theme: string) => void;
  /** First-column +/✓ watchlist toggle (off on Positions, where the row menu handles moves). */
  watchColumn?: boolean;
  priceLabel?: string;
  /** Columns before the price column. */
  leadColumns?: ExtraColumn[];
  /** Columns right after the price column. */
  extraColumns?: ExtraColumn[];
  /** Trailing per-row action cell. */
  actions?: (r: ScanRow) => ReactNode;
  actionsLabel?: string;
  /** Chart timeframe to switch the detail page to when a row is clicked; omitted keeps its sticky choice. */
  detailTf?: Tf | null;
  /** The Min RS slider as a 0..1 percentile, used to label leaders that have no weekly setup. */
  minRs?: number;
  /** Sort the table starts in (default: score, highest first). */
  initialSort?: { key: string; dir: 1 | -1 };
  /** Symbol search text: the row whose ticker equals it is shown first, whatever the sort. */
  pinSymbol?: string;
  /**
   * Trading-list layout (Watchlist and Positions, via ListTable): drops the scanning-only columns,
   * 1M / 3M / 6M returns, D · W · M continuity and Weekly setup. Its Day column comes from ListTable instead.
   */
  tradingList?: boolean;
  /** Per-row highlight (extra class on the row, and its tooltip). */
  rowHighlight?: (r: ScanRow) => { className: string; title: string } | null;
}

export function ScanTable({
  rows,
  onTheme,
  watchColumn = true,
  priceLabel = "Price",
  leadColumns = [],
  extraColumns = [],
  actions,
  actionsLabel = "Actions",
  minRs = LEADER_RS,
  initialSort = { key: "score", dir: -1 },
  detailTf,
  pinSymbol = "",
  rowHighlight,
  tradingList = false,
}: Props) {
  const scanning = !tradingList;
  const navigate = useNavigate();
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>(initialSort);
  const custom = useMemo(() => [...leadColumns, ...extraColumns], [leadColumns, extraColumns]);
  const sorted = useMemo(() => {
    const col = custom.find((c) => c.key === sort.key);
    const out = col ? sortBy(rows, col.sortValue, sort.dir) : sortRows(rows, sort.key as SortKey, sort.dir);
    return pinExactSymbol(out, pinSymbol);
  }, [rows, sort, custom, pinSymbol]);

  const ascendingFirst = (key: string) =>
    custom.find((c) => c.key === key)?.ascendingFirst ?? ASCENDING_FIRST.includes(key as SortKey);

  const header = (key: string, label: string, cls = "", title?: string) => (
    <th
      key={key}
      title={title}
      className={`sortable ${cls} ${sort.key === key ? "active" : ""}`}
      onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : ascendingFirst(key) ? 1 : -1 }))}
    >
      {label}
      {sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </th>
  );

  return (
    <div className="card table-card">
      <table className="scan-table">
        <thead>
          <tr>
            {watchColumn && <th className="watch-col" aria-label="Watchlist" />}
            <th className="rank">#</th>
            {header("symbol", "Symbol")}
            {header("theme", "Theme")}
            {leadColumns.map((c) => header(c.key, c.label, c.className))}
            {header("price", priceLabel, "num")}
            {extraColumns.map((c) => header(c.key, c.label, c.className))}
            {scanning && header("change_pct", "Day", "num")}
            {scanning && PERF_PERIODS.map((p) => header(`perf_${p.key}`, p.label, "num perf-col"))}
            {scanning && <th>D · W · M</th>}
            {scanning && <th>Weekly setup</th>}
            <th className="num">Trigger</th>
            {header("trigger_distance_pct", "To trigger", "num")}
            {header("avg_dollar_volume", "Avg $vol", "num")}
            {header("atr", "ATR", "num", "14-day average true range")}
            {header("atr_pct", "ATR %", "num", "14-day ATR as a percent of price")}
            {header("score", "Score", actions ? "num" : "num score-col")}
            {actions && <th className="actions-col">{actionsLabel}</th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const trend = dailyTrendBadge(r.daily_trend);
            const weeklyTrend = weeklyTrendBadge(r.weekly_trend);
            const chip = triggerChip({ triggered: r.triggered, live: r.triggered_live, trigger: r.trigger });
            const mark = rowHighlight?.(r) ?? null;
            return (
            <tr key={r.symbol} className={mark?.className} title={mark?.title} onClick={() => {
              if (detailTf) writePersisted(DETAIL_TF_KEY, detailTf);
              navigate(`/stock/${r.symbol}`);
            }}>
              {watchColumn && (
                <td className="watch-col">
                  <WatchButton symbol={r.symbol} />
                </td>
              )}
              <td className="rank muted">{i + 1}</td>
              <td>
                <div className="sym sym-with-logo">
                  <TickerLogo symbol={r.symbol} size={20} />
                  {r.symbol}
                  <EarningsIcon earnings={r.earnings} />
                  {r.kind === "etf" && (isIndexEtf(r) ? <span className="etf-chip index-chip" title="Index ETF: always listed in the ETFs view">INDEX</span> : <span className="etf-chip">ETF</span>)}
                  <RsChip row={r} />
                  {r.in_universe === false && <AddedChip />}
                </div>
                <div className="sub muted sym-sub">{r.name}</div>
              </td>
              <td className="muted small theme-cell">
                {r.theme && r.theme_name ? (
                  onTheme ? (
                    <span className="sector-link" title={`Scan ${r.theme_name}`} onClick={(e) => { e.stopPropagation(); onTheme(r.theme!); }}>
                      {r.theme_name}
                    </span>
                  ) : (
                    r.theme_name
                  )
                ) : (
                  "—"
                )}
              </td>
              {leadColumns.map((c) => (
                <td key={c.key} className={c.className}>
                  {c.render(r)}
                </td>
              ))}
              <td className="num">{r.price.toFixed(2)}</td>
              {extraColumns.map((c) => (
                <td key={c.key} className={c.className}>
                  {c.render(r)}
                </td>
              ))}
              {scanning && <DayCell row={r} />}
              {scanning && PERF_PERIODS.map((p) => (
                <td key={p.key} className={`num perf-col ${perfClass(r.perf?.[p.key])}`}>
                  {fmtPerf(r.perf?.[p.key])}
                </td>
              ))}
              {scanning && (
                <td>
                  <TfBadges tf={r.tf} />
                </td>
              )}
              {scanning && (
              <td className="setup-cell">
                {trend && (
                  <span className={`trend-badge ${trend.tone}`} title={trend.title}>
                    {trend.label}
                  </span>
                )}
                {weeklyTrend && (
                  <span className={`trend-badge ${weeklyTrend.tone}`} title={weeklyTrend.title}>
                    {weeklyTrend.label}
                  </span>
                )}
                {r.breakout && !r.failed_breakout && (
                  <span
                    className="breakout-badge"
                    title={`Weekly close ${r.breakout.close.toFixed(2)} above the ${r.breakout.base_high.toFixed(2)} base high on ${r.breakout.volume_x.toFixed(1)}x average weekly volume, closing ${Math.round(r.breakout.close_position * 100)}% up the week's range`}
                  >
                    {breakoutLabel(r.breakout)}
                  </span>
                )}
                {r.failed_breakout && (
                  <span
                    className="breakout-badge failed"
                    title={`Breakout level ${r.failed_breakout.level.toFixed(2)}: weekly close ${r.failed_breakout.breakout_close.toFixed(2)} above the base high on ${r.failed_breakout.volume_x.toFixed(1)}x average weekly volume, then closed back below it on ${r.failed_breakout.failed_on}; ${r.failed_breakout.sessions_below} session(s) below since, deepest close ${fmtPct(r.failed_breakout.low_pct)} vs the level`}
                  >
                    {failedBreakoutLabel(r.failed_breakout)}
                  </span>
                )}
                {r.has_setup && r.setup ? (
                  <>
                    <div className={r.triggered ? "setup triggered" : "setup"}>
                      {r.setup}
                      {chip && (
                        <span className="trig-chip" title={chip.title}>
                          {chip.label}
                        </span>
                      )}
                    </div>
                    <div className="sub muted reason" title={r.reason}>
                      {r.reason.split(" · ").slice(1).join(" · ")}
                    </div>
                  </>
                ) : (
                  <>
                    <span className={noSetupLabel(r, minRs) === NO_SETUP_LEADER ? "no-setup leader" : "no-setup"}>{noSetupLabel(r, minRs)}</span>
                    <div className="sub muted reason" title={r.reason}>
                      {r.reason.split(" · ").filter((s) => !s.startsWith("No weekly")).join(" · ")}
                    </div>
                  </>
                )}
              </td>
              )}
              <TriggerCells row={r} />
              <td className="num muted">{fmtMoney(r.avg_dollar_volume)}</td>
              <td className="num">{r.atr == null ? "—" : r.atr.toFixed(2)}</td>
              <td className="num">{r.atr_pct == null ? "—" : `${r.atr_pct.toFixed(2)}%`}</td>
              <td className={actions ? "num" : "num score-col"}>
                <ScorePill score={r.score} row={r} />
              </td>
              {actions && (
                <td className="actions-col" onClick={(e) => e.stopPropagation()}>
                  {actions(r)}
                </td>
              )}
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
