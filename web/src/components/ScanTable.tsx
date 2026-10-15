import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fmtMoney, fmtPct, type ScanRow } from "../api";
import { fmtCompact } from "../logScale";
import { NO_SETUP_LABEL } from "../watchlist";
import { ScorePill, TfBadges } from "./Badges";
import { WatchButton, useWatchlist } from "./Watch";

export type SortKey =
  | "score"
  | "symbol"
  | "price"
  | "change_pct"
  | "trigger_distance_pct"
  | "avg_dollar_volume"
  | "avg_volume"
  | "sector";

export function sortRows(rows: ScanRow[], key: SortKey, dir: 1 | -1): ScanRow[] {
  // Distance sorts by closeness to the trigger, whichever side of it price is on.
  const value = (r: ScanRow) =>
    key === "trigger_distance_pct" && r.trigger_distance_pct !== null ? Math.abs(r.trigger_distance_pct) : r[key];
  return [...rows].sort((a, b) => {
    const av = value(a);
    const bv = value(b);
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (typeof av === "string" && typeof bv === "string") return av.localeCompare(bv) * dir;
    return ((av as number) - (bv as number)) * dir;
  });
}

const ASCENDING_FIRST: SortKey[] = ["symbol", "sector", "trigger_distance_pct"];

export function ScanTable({
  rows,
  onSector,
  removable = false,
}: {
  rows: ScanRow[];
  onSector?: (sector: string) => void;
  removable?: boolean;
}) {
  const navigate = useNavigate();
  const { toggle } = useWatchlist();
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "score", dir: -1 });
  const sorted = useMemo(() => sortRows(rows, sort.key, sort.dir), [rows, sort]);

  const header = (key: SortKey, label: string, cls = "") => (
    <th
      className={`sortable ${cls} ${sort.key === key ? "active" : ""}`}
      onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : ASCENDING_FIRST.includes(key) ? 1 : -1 }))}
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
            <th className="watch-col" aria-label="Watchlist" />
            <th className="rank">#</th>
            {header("symbol", "Symbol")}
            {header("sector", "Sector")}
            {header("price", "Price", "num")}
            {header("change_pct", "Day", "num")}
            <th>M · W · D</th>
            <th>Weekly setup</th>
            <th className="num">Trigger</th>
            {header("trigger_distance_pct", "To trigger", "num")}
            {header("avg_volume", "Avg vol", "num")}
            {header("avg_dollar_volume", "Avg $vol", "num")}
            {header("score", "Score", "num")}
            {removable && <th aria-label="Remove" />}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={r.symbol} onClick={() => navigate(`/stock/${r.symbol}`)}>
              <td className="watch-col">
                <WatchButton symbol={r.symbol} />
              </td>
              <td className="rank muted">{i + 1}</td>
              <td>
                <div className="sym">
                  {r.symbol}
                  {r.kind === "etf" && <span className="etf-chip">ETF</span>}
                </div>
                <div className="sub muted">{r.name}</div>
              </td>
              <td className="muted small">
                {onSector ? (
                  <span className="sector-link" onClick={(e) => { e.stopPropagation(); onSector(r.sector); }}>
                    {r.sector}
                  </span>
                ) : (
                  r.sector
                )}
              </td>
              <td className="num">{r.price.toFixed(2)}</td>
              <td className={`num ${r.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(r.change_pct, 2)}</td>
              <td>
                <TfBadges tf={r.tf} />
              </td>
              <td className="setup-cell">
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
                    <span className="no-setup">{NO_SETUP_LABEL}</span>
                    <div className="sub muted reason" title={r.reason}>
                      {r.reason.split(" · ").filter((s) => !s.startsWith("No weekly")).join(" · ")}
                    </div>
                  </>
                )}
              </td>
              <td className="num accent-text">{r.trigger?.toFixed(2) ?? "—"}</td>
              <td className="num">{fmtPct(r.trigger_distance_pct)}</td>
              <td className="num">{fmtCompact(r.avg_volume)}</td>
              <td className="num muted">{fmtMoney(r.avg_dollar_volume)}</td>
              <td className="num">
                <ScorePill score={r.score} row={r} />
              </td>
              {removable && (
                <td>
                  <button
                    type="button"
                    className="btn remove-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(r.symbol);
                    }}
                  >
                    ✕ Remove
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
