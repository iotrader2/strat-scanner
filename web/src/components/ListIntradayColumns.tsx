import type { ListIntraday, ScanRow } from "../api";
import { fmtPct } from "../api";
import { emaDistance, emaSide, fmtVolume, premarketTitle, rangeTitle, rangeTone } from "../listIntraday";
import type { ExtraColumn } from "./ScanTable";

type Intraday = Record<string, ListIntraday> | undefined;

function Dash({ title }: { title: string }) {
  return (
    <span className="muted" title={title}>
      —
    </span>
  );
}

function EmaCell({ info, period }: { info: ListIntraday | undefined; period: 6 | 20 }) {
  const em = info?.ema5m;
  if (!em) return <Dash title={`No 5-minute ${period} EMA yet`} />;
  const view = emaSide(em, period);
  return (
    <span className={`ema-pill ${view.side}`} title={view.title}>
      {view.label}
    </span>
  );
}

function DayRangeCell({ info }: { info: ListIntraday | undefined }) {
  const r = info?.day_range;
  if (!r) return <Dash title="No day range yet (or high equals low)" />;
  const pct = Math.min(100, Math.max(0, r.pct));
  const tone = rangeTone(pct);
  return (
    <span className={`day-range ${tone}`} title={rangeTitle(r)}>
      <span className="dr-track">
        <span className="dr-marker" style={{ left: `${pct}%` }} />
      </span>
      <span className="dr-pct">
        {r.basis === "premarket" && <span className="pm-tag">PM</span>}
        {Math.round(pct)}%
      </span>
    </span>
  );
}

/** Premarket, Day, Day range, 6 EMA (5m) and 20 EMA (5m) columns for the watchlist and positions tables. */
export function listIntradayColumns(intraday: Intraday): ExtraColumn[] {
  const get = (r: ScanRow) => intraday?.[r.symbol];
  return [
    {
      key: "premarket",
      label: "Premkt",
      className: "num premkt-col",
      sortValue: (r) => get(r)?.premarket?.change_pct ?? null,
      render: (r) => {
        const pm = get(r)?.premarket;
        if (!pm) return <Dash title="No premarket print (shown 4:00 AM to 4:00 PM ET)" />;
        return (
          <span title={premarketTitle(pm)}>
            <div>
              {pm.final && <span className="pm-tag">PM</span>}
              {pm.price.toFixed(2)}
            </div>
            <div className={`sub ${pm.change_pct >= 0 ? "green-text" : "red-text"}`}>{fmtPct(pm.change_pct, 2)}</div>
            {pm.volume !== null && <div className="sub muted">vol {fmtVolume(pm.volume)}</div>}
          </span>
        );
      },
    },
    {
      // Same sort key as the scanner's Day column; rendered here so it sits next to Day range.
      key: "change_pct",
      label: "Day",
      className: "num",
      sortValue: (r) => r.change_pct,
      render: (r) => <span className={r.change_pct >= 0 ? "green-text" : "red-text"}>{fmtPct(r.change_pct, 2)}</span>,
    },
    {
      key: "day_range",
      label: "Day range",
      className: "range-col",
      sortValue: (r) => get(r)?.day_range?.pct ?? null,
      render: (r) => <DayRangeCell info={get(r)} />,
    },
    {
      key: "ema6_5m",
      label: "6 EMA (5m)",
      className: "ema-col",
      sortValue: (r) => emaDistance(get(r)?.ema5m, 6),
      render: (r) => <EmaCell info={get(r)} period={6} />,
    },
    {
      key: "ema20_5m",
      label: "20 EMA (5m)",
      className: "ema-col",
      sortValue: (r) => emaDistance(get(r)?.ema5m, 20),
      render: (r) => <EmaCell info={get(r)} period={20} />,
    },
  ];
}
