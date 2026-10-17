import { useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { fmtMoney, fmtPct, type ScanRow } from "../api";
import { fmtCompact } from "../logScale";
import { fmtPerf, isPerfSort, perfClass, perfSortValue, PERF_PERIODS, type PerfSort } from "../perf";
import { breakoutLabel, fmtRs, LEADER_RS, NO_SETUP_LEADER, noSetupLabel, triggerHint } from "../leadership";
import { AddedChip, ScorePill, TfBadges } from "./Badges";
import { EarningsIcon } from "./EarningsIcon";
import { WatchButton } from "./Watch";

/** Relative-strength percentile chip, with a flag when the leader is weakening or its trend is broken. */
function RsChip({ row }: { row: ScanRow }) {
  if (row.rs === null || row.rs === undefined) return null;
  const level = row.leadership?.breakdown ?? "none";
  const kill = row.kill_candle && row.kill_candle.penalty > 0 ? ` · kill candle ${row.kill_candle.date.slice(5)}` : "";
  const flag = (level === "broken" ? " · broken" : level === "warning" ? " · weakening" : "") + kill;
  const reasons = row.leadership?.breakdown_reasons ?? [];
  const title = `Relative strength ${fmtRs(row.rs)}: blended 1M/3M/6M return percentile${reasons.length ? `. ${reasons.join("; ")}` : ""}`;
  return (
    <span className={`rs-chip ${level}`} title={title}>
      RS {Math.round(row.rs * 100)}
      {flag}
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

export type SortKey =
  | "score"
  | "symbol"
  | "price"
  | "change_pct"
  | "trigger_distance_pct"
  | "avg_dollar_volume"
  | "avg_volume"
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
export function sortBy(rows: ScanRow[], value: (r: ScanRow) => unknown, dir: 1 | -1): ScanRow[] {
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
  /** The Min RS slider as a 0..1 percentile, used to label leaders that have no weekly setup. */
  minRs?: number;
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
}: Props) {
  const navigate = useNavigate();
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "score", dir: -1 });
  const custom = useMemo(() => [...leadColumns, ...extraColumns], [leadColumns, extraColumns]);
  const sorted = useMemo(() => {
    const col = custom.find((c) => c.key === sort.key);
    return col ? sortBy(rows, col.sortValue, sort.dir) : sortRows(rows, sort.key as SortKey, sort.dir);
  }, [rows, sort, custom]);

  const ascendingFirst = (key: string) =>
    custom.find((c) => c.key === key)?.ascendingFirst ?? ASCENDING_FIRST.includes(key as SortKey);

  const header = (key: string, label: string, cls = "") => (
    <th
      key={key}
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
            {header("change_pct", "Day", "num")}
            {PERF_PERIODS.map((p) => header(`perf_${p.key}`, p.label, "num perf-col"))}
            <th>M · W · D</th>
            <th>Weekly setup</th>
            <th className="num">Trigger</th>
            {header("trigger_distance_pct", "To trigger", "num")}
            {header("avg_volume", "Avg vol", "num")}
            {header("avg_dollar_volume", "Avg $vol", "num")}
            {header("score", "Score", actions ? "num" : "num score-col")}
            {actions && <th className="actions-col">{actionsLabel}</th>}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={r.symbol} onClick={() => navigate(`/stock/${r.symbol}`)}>
              {watchColumn && (
                <td className="watch-col">
                  <WatchButton symbol={r.symbol} />
                </td>
              )}
              <td className="rank muted">{i + 1}</td>
              <td>
                <div className="sym">
                  {r.symbol}
                  <EarningsIcon earnings={r.earnings} />
                  {r.kind === "etf" && <span className="etf-chip">ETF</span>}
                  <RsChip row={r} />
                  {r.in_universe === false && <AddedChip />}
                </div>
                <div className="sub muted">{r.name}</div>
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
              <td className={`num ${r.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(r.change_pct, 2)}</td>
              {PERF_PERIODS.map((p) => (
                <td key={p.key} className={`num perf-col ${perfClass(r.perf?.[p.key])}`}>
                  {fmtPerf(r.perf?.[p.key])}
                </td>
              ))}
              <td>
                <TfBadges tf={r.tf} />
              </td>
              <td className="setup-cell">
                {r.breakout && (
                  <span
                    className="breakout-badge"
                    title={`Weekly close ${r.breakout.close.toFixed(2)} above the ${r.breakout.base_high.toFixed(2)} base high on ${r.breakout.volume_x.toFixed(1)}x average weekly volume, closing ${Math.round(r.breakout.close_position * 100)}% up the week's range`}
                  >
                    {breakoutLabel(r.breakout)}
                  </span>
                )}
                {r.has_setup && r.setup ? (
                  <>
                    <div className={r.triggered ? "setup triggered" : "setup"}>
                      {r.setup}
                      {r.triggered && <span className="trig-chip">triggered</span>}
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
              <TriggerCells row={r} />
              <td className="num">{fmtCompact(r.avg_volume)}</td>
              <td className="num muted">{fmtMoney(r.avg_dollar_volume)}</td>
              <td className={actions ? "num" : "num score-col"}>
                <ScorePill score={r.score} row={r} />
              </td>
              {actions && (
                <td className="actions-col" onClick={(e) => e.stopPropagation()}>
                  {actions(r)}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
