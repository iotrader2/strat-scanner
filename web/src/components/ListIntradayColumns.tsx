import type { ListIntraday, ScanRow } from "../api";
import { fmtPct } from "../api";
import { emaDistance, emaSide, fmtVolume, premarketTitle } from "../listIntraday";
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

/** Premarket, 6 EMA (5m) and 20 EMA (5m) columns for the watchlist and positions tables. */
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
