import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type AlertHistoryPayload,
  type AlertMetricRow,
  type AlertStatus,
  type AlertMetricsPayload,
  type AlertSettings,
  type AlertSettingsPayload,
  type AlertsPayload,
  type TradeAlert,
} from "../api";
import {
  SETTING_GROUPS,
  SETUP_NAMES,
  isShortAlert,
  SETUP_RULES,
  STATUS_LABEL,
  alertDayStatus,
  ALERT_SORT_KEYS,
  METRIC_SORT_KEYS,
  alertSortValue,
  dailySetupText,
  happenedText,
  normalizeColumnSort,
  setupPeriod,
  type ColumnSort,
  sortByColumn,
  toggleColumnSort,
  fmtR,
  maText,
  maTitle,
  phoenixTime,
  rTone,
  riskPerShare,
  statusTone,
  stopPct,
  todayEmptyLead,
  DEFAULT_ALERT_FILTERS,
  alertFiltersActive,
  filterAlerts,
  normalizeAlertFilters,
  rsLevel,
  type AlertDayStatus,
  type AlertFilters,
} from "../alerts";
import { useAlerts } from "../components/AlertsCenter";
import { EntryModal, Modal } from "../components/Modal";
import { usePositions } from "../components/Positions";
import { ScorePill } from "../components/ScoreBreakdown";
import { EarningsIcon } from "../components/EarningsIcon";
import { TickerLogo } from "../components/TickerLogo";
import { INTRADAY_EMA_COLORS } from "../intradayChart";
import { usePersisted } from "../persist";
import { Pager } from "../components/Pager";
import { normalizePageSize, paginate } from "../pagination";
import { fmtRs } from "../leadership";
import { AtrSlider } from "../components/AtrSlider";
import { LogSlider } from "../components/LogSlider";
import { RangeSlider } from "../components/RangeSlider";
import { normalizeAtrRange, type AtrRange } from "../atrFilter";
import { DOLLAR_VOL_RANGE, fmtCompact } from "../logScale";

/** The EMA's line color on the 15-minute chart: 120 red, 240 yellow, 480 blue. */
function emaColor(setup: string): string | undefined {
  const p = Number(setupPeriod(setup)) as keyof typeof INTRADAY_EMA_COLORS;
  return INTRADAY_EMA_COLORS[p];
}

function EmaDot({ setup }: { setup: string }) {
  const color = emaColor(setup);
  return color ? <i className="ema-dot" style={{ background: color }} aria-hidden="true" /> : null;
}

const money = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));

function AttentionControls() {
  const { soundReady, muted, setMuted, enableSound, notifyPermission, enableNotifications } = useAlerts();
  return (
    <div className="alert-controls" role="group" aria-label="Alert sound and notifications">
      {!soundReady ? (
        <button type="button" className="btn small primary" onClick={enableSound} title="Browsers only play sound after a click on the page">
          Enable sound
        </button>
      ) : (
        <button type="button" className={`btn small ${muted ? "" : "primary"}`} onClick={() => setMuted(!muted)} aria-pressed={muted}>
          {muted ? "Sound muted" : "Sound on"}
        </button>
      )}
      {notifyPermission === "default" && (
        <button type="button" className="btn small" onClick={enableNotifications} title="Show a notification when an alert fires while this tab is in the background">
          Enable notifications
        </button>
      )}
      {notifyPermission === "granted" && <span className="muted small">Background notifications on</span>}
      {notifyPermission === "denied" && <span className="muted small">Notifications blocked in the browser</span>}
      {notifyPermission === "unsupported" && (
        <span className="muted small">No notifications here (on iPad, add TiltKiller to the Home Screen)</span>
      )}
    </div>
  );
}

function StatusPill({ a }: { a: TradeAlert }) {
  return <span className={`alert-status ${statusTone(a)}`}>{STATUS_LABEL[a.status]}</span>;
}

/** Last price to offer as the buy: the fill when the stop already triggered, otherwise the buy stop. */
function entryPrice(a: TradeAlert): number {
  return a.fill_price ?? a.trigger_price;
}

function AlertScore({ a }: { a: TradeAlert }) {
  if (a.score == null) return <span className="muted">—</span>;
  const row =
    a.score_raw != null && a.score_max_raw != null
      ? { score: a.score, score_raw: a.score_raw, score_max_raw: a.score_max_raw, score_breakdown: a.score_breakdown ?? [] }
      : undefined;
  return <ScorePill score={a.score} row={row} />;
}

/** RS percentile as a pill, coloured on the same cuts as the score pill. */
export function RsPill({ rs }: { rs: number | null | undefined }) {
  if (rs == null) return <span className="muted">—</span>;
  return <span className={`score-pill ${rsLevel(rs)}`}>{fmtRs(rs)}</span>;
}

const SIDE_OPTIONS: { value: AlertFilters["side"]; label: string }[] = [
  { value: "all", label: "All" },
  { value: "long", label: "Long" },
  { value: "short", label: "Short" },
];

const STATUS_OPTIONS: { value: AlertFilters["status"]; label: string }[] = [
  { value: "all", label: "All" },
  ...(Object.entries(STATUS_LABEL) as [AlertStatus, string][]).map(([value, label]) => ({ value, label })),
];

/** Score and RS range sliders plus a Long / Short toggle, shared by the live and history tables. */
export function AlertFilterBar({
  filters,
  onChange,
  ticker,
  onTicker,
  shown,
  total,
}: {
  filters: AlertFilters;
  onChange: (f: AlertFilters) => void;
  ticker: string;
  onTicker: (q: string) => void;
  shown: number;
  total: number;
}) {
  const active = alertFiltersActive(filters) || ticker.trim() !== "";
  return (
    <div className="card alert-filters filter-sliders">
      <div className="field alert-ticker-filter">
        <label className="slider-head" htmlFor="alert-ticker-search">
          Ticker
        </label>
        <input
          id="alert-ticker-search"
          className="input"
          type="search"
          placeholder="Search, e.g. MRNA"
          value={ticker}
          onChange={(e) => onTicker(e.target.value.toUpperCase())}
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
        />
      </div>
      <div className="field alert-side-filter">
        <span className="slider-head">Side</span>
        <div className="seg" role="group" aria-label="Side">
          {SIDE_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              className={filters.side === o.value ? "active" : ""}
              aria-pressed={filters.side === o.value}
              onClick={() => onChange({ ...filters, side: o.value })}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>
      <div className="field alert-status-filter">
        <span className="slider-head">Status</span>
        <div className="seg" role="group" aria-label="Status">
          {STATUS_OPTIONS.map((o) => (
            <button
              key={o.value}
              type="button"
              className={filters.status === o.value ? "active" : ""}
              aria-pressed={filters.status === o.value}
              onClick={() => onChange({ ...filters, status: o.value })}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>
      <RangeSlider label="Score" min={0} max={100} value={filters.score} onChange={(score) => onChange({ ...filters, score })} />
      <RangeSlider
        label="RS"
        min={0}
        max={100}
        format={(v) => `P${v}`}
        value={filters.rs}
        onChange={(rs) => onChange({ ...filters, rs })}
      />
      <div className="alert-filter-meta">
        <span className="muted small">
          {active ? `${shown} of ${total} shown` : `${total} alerts`}
        </span>
        {active && (
          <button
            type="button"
            className="btn small ghost"
            onClick={() => {
              onChange(DEFAULT_ALERT_FILTERS);
              onTicker("");
            }}
          >
            Clear filters
          </button>
        )}
      </div>
    </div>
  );
}

/** Persisted alert filters (one setting for the live and history tables). */
function useAlertFilters() {
  const [raw, setRaw] = usePersisted<AlertFilters>("alertFilters", DEFAULT_ALERT_FILTERS);
  return [normalizeAlertFilters(raw), setRaw] as const;
}

function SortableTh({
  label,
  title,
  className,
  active,
  dir,
  onClick,
}: {
  label: string;
  title?: string;
  className?: string;
  active: boolean;
  dir: 1 | -1;
  onClick: () => void;
}) {
  return (
    <th
      className={`sortable${className ? ` ${className}` : ""}${active ? " active" : ""}`}
      title={title}
      aria-sort={active ? (dir === 1 ? "ascending" : "descending") : "none"}
      onClick={onClick}
    >
      {label}
      {active ? (dir === 1 ? "\u00a0▲" : "\u00a0▼") : ""}
    </th>
  );
}

export function AlertsTable({
  alerts,
  flashing,
  onAck,
  onBought,
  readOnly = false,
  sortStorageKey = "alertsTableSort",
}: {
  alerts: TradeAlert[];
  flashing: Set<number>;
  onAck: (id: number) => void;
  onBought: (alert: TradeAlert) => void;
  /** History rows keep the same columns and do not acknowledge or record a buy. */
  readOnly?: boolean;
  /** localStorage key so the live table and history remember their sorts separately. */
  sortStorageKey?: string;
}) {
  const [stored, setStored] = usePersisted<ColumnSort | null>(sortStorageKey, null);
  const sort = normalizeColumnSort(stored, ALERT_SORT_KEYS);
  const ordered = useMemo(() => sortByColumn(alerts, sort, alertSortValue), [alerts, sort]);
  const [storedSize, setStoredSize] = usePersisted<number>(`${sortStorageKey}PageSize`, 50);
  const pageSize = normalizePageSize(storedSize);
  // Not persisted: a reload starts on page 1. A page past the end (after filtering) shows the last page.
  const [page, setPage] = useState(0);
  const slice = useMemo(() => paginate(ordered, page, pageSize), [ordered, page, pageSize]);
  const header = (key: (typeof ALERT_SORT_KEYS)[number], label: string, className?: string, title?: string) => (
    <SortableTh
      key={key}
      label={label}
      title={title}
      className={className}
      active={sort?.key === key}
      dir={sort?.dir ?? 1}
      onClick={() => {
        setStored(toggleColumnSort(sort, key));
        setPage(0);
      }}
    />
  );
  const pager = (
    <Pager
      id={sortStorageKey}
      slice={slice}
      size={pageSize}
      onPage={setPage}
      onSize={(n) => {
        setStoredSize(n);
        setPage(0);
      }}
    />
  );
  return (
    <>
    <div className="card table-card">
      <table className="scan-table alerts-table">
        <thead>
          <tr>
            {header("fired_at", "Watch", undefined, "When the 15-minute candle that touched the EMA closed")}
            {header("symbol", "Ticker")}
            {header("score", "Score", "num")}
            {header("rs", "RS", "num", "Relative strength percentile, as on the Stock Scanner")}
            {header("side", "Side")}
            {header("daily_setup", "Daily setup", undefined, "The daily setup(s) that put this name on the alert list")}
            {header("industry", "Industry", undefined, "Industry, and its rank among stock industries by median RS (1 = strongest)")}
            {header("entry", "Entry")}
            {header("ema", "EMA", "num", "The EMA's value on the touch candle")}
            {header("trigger", "Trigger", "num", "Previous 15-minute candle high + 1c (short: low - 1c)")}
            {header("stop", "Stop", "num")}
            {header("stop_pct", "Stop %", "num")}
            {header("risk", "Risk / sh", "num")}
            {header("status", "Status")}
            {header("best", "Best", "num", "Best price since the fill: the high (short: the low)")}
            {header("open_r", "Open R", "num", "Open trades (triggered, not stopped or exited): R at the last price")}
            {header("r", "R", "num", "Closed trades: R at the exit. Highest first.")}
            {header("outcome", "What happened", "outcome-cell")}
            <th className="bought-col" aria-label="Bought" />
            <th className="actions-col" aria-label="Acknowledge" />
          </tr>
        </thead>
        <tbody>
          {slice.rows.map((a) => (
            <tr
              key={a.id}
              className={`alert-row ${a.acknowledged ? "read" : "unread"} ${flashing.has(a.id) ? "flash" : ""}`}
              data-alert-id={a.id}
            >
              <td className="nowrap">
                {phoenixTime(a.fired_at)}
                {a.late && <span className="late-chip" title="Found after the fact (restart or missed poll); no chime">late</span>}
              </td>
              <td>
                <Link className="sym sym-with-logo" to={`/stock/${encodeURIComponent(a.symbol)}`}>
                  <TickerLogo symbol={a.symbol} size={20} />
                  {a.symbol}
                  {a.details?.underlying && (
                    <span className="muted small" title="Underlying for this inverse ETF short">
                      {" "}← {String(a.details.underlying)}
                    </span>
                  )}
                  <EarningsIcon earnings={a.earnings} />
                  {a.top && <span className="top-chip">TOP</span>}
                </Link>
              </td>
              <td className="num">
                <AlertScore a={a} />
              </td>
              <td className="num">
                <RsPill rs={a.rs} />
              </td>
              <td>
                <span className={`side-chip ${isShortAlert(a) ? "short" : "long"}`}>
                  {isShortAlert(a) ? "SHORT" : "LONG"}
                </span>
              </td>
              <td className="daily-setup-cell">
                {dailySetupText(a.details?.daily_setups) || <span className="muted">—</span>}
              </td>
              <td className="industry-cell">
                {a.industry ? (
                  <>
                    <span className="industry-name">{a.industry}</span>
                    {a.industry_rank != null && (
                      <span className="muted small industry-rank" title={`Rank ${a.industry_rank} of ${a.industry_total} industries by median RS`}>
                        #{a.industry_rank}/{a.industry_total}
                      </span>
                    )}
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                <span className="setup-hover" title={SETUP_RULES[a.setup]}>
                  <span className="setup-letter">
                    <EmaDot setup={a.setup} />
                    {setupPeriod(a.setup)}
                  </span>
                  <span className="muted small setup-name">{SETUP_NAMES[a.setup] ?? `Setup ${a.setup}`}</span>
                </span>
              </td>
              <td className="num" title={maTitle(a)}>
                {maText(a)}
              </td>
              <td className="num">{money(a.trigger_price)}</td>
              <td className="num">{money(a.stop_price)}</td>
              <td className="num">{stopPct(a).toFixed(2)}%</td>
              <td className="num">{money(riskPerShare(a))}</td>
              <td>
                <StatusPill a={a} />
              </td>
              <td className="num">{money(a.high_reached)}</td>
              <td
                className={`num open-r ${rTone(a.open_r)}`}
                title={a.open_r != null && a.price != null ? `At ${money(a.price)}` : undefined}
              >
                {fmtR(a.open_r)}
              </td>
              <td className={`num ${rTone(a.r_multiple)}`}>
                {fmtR(a.r_multiple)}
              </td>
              <td className="muted small outcome-cell">{happenedText(a)}</td>
              <td className="bought-col">
                {readOnly ? (
                  <span className="muted small">—</span>
                ) : (
                  <button
                    type="button"
                    className="btn small move-btn"
                    onClick={() => onBought(a)}
                    title="Record the entry and track it on the Positions tab"
                  >
                    {isShortAlert(a) ? "Shorted →" : "Bought →"}
                  </button>
                )}
              </td>
              <td className="actions-col">
                {readOnly ? (
                  <span className="muted small">{a.acknowledged ? "Read" : "—"}</span>
                ) : !a.acknowledged ? (
                  <button type="button" className="btn small" onClick={() => onAck(a.id)}>
                    <span className="ack-long">Acknowledge</span>
                    <span className="ack-short">Ack</span>
                  </button>
                ) : (
                  <span className="muted small">Read</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    {slice.total > 25 && pager}
    </>
  );
}

export function AlertDayBanner({ status }: { status: AlertDayStatus }) {
  return (
    <div className={`alert-day ${status.phase}`} role="status">
      <div className="alert-day-headline">{status.headline}</div>
      <p className="muted small alert-day-detail">{status.detail}</p>
      <ul className="alert-day-windows">
        {status.windows.map((w) => (
          <li key={w.setup} className={`alert-window-chip ${w.state}`}>
            <span className="setup-letter">
              <EmaDot setup={w.setup} />
              {w.setup} EMA
            </span>
            <span>{w.label}</span>
            {status.phase === "open" && w.state === "done" && <span className="alert-window-state">done</span>}
            {w.state === "open" && <span className="alert-window-state">open</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AlertsView({ day }: { day: AlertDayStatus }) {
  const { today, flashing, acknowledge, error: liveError, reload } = useAlerts();
  const { open } = usePositions();
  const [moving, setMoving] = useState<TradeAlert | null>(null);
  const [session, setSession] = useState<string>("today");
  const [other, setOther] = useState<AlertsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session === "today") return;
    setOther(null);
    api.alerts(session).then(setOther).catch((e) => setError(String(e)));
  }, [session]);

  const view = session === "today" ? today : other;
  const sessions = today?.sessions ?? [];
  const ack = useCallback(
    async (ids?: number[]) => {
      await acknowledge(ids);
      if (session !== "today") api.alerts(session).then(setOther).catch(() => undefined);
    },
    [acknowledge, session],
  );
  const [filters, setFilters] = useAlertFilters();
  const [ticker, setTicker] = useState("");
  const shownAlerts = useMemo(() => filterAlerts(view?.alerts ?? [], filters, ticker), [view, filters, ticker]);
  const unreadHere = (view?.alerts ?? []).filter((a) => !a.acknowledged).length;
  const filled = (view?.alerts ?? []).filter((a) => a.filled).length;
  const emptyLead = session === "today" ? todayEmptyLead(day) : null;

  return (
    <>
      <div className="table-meta alerts-toolbar">
        <div className="alerts-toolbar-left">
          <label className="muted small" htmlFor="alert-session">
            Session
          </label>
          <select id="alert-session" className="input select" value={session} onChange={(e) => setSession(e.target.value)}>
            <option value="today">Today{today ? ` (${today.session})` : ""}</option>
            {sessions
              .filter((s) => s !== today?.session)
              .map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
          </select>
          {view && (
            <span className="muted small">
              {view.alerts.length} alerts · {filled} filled · {unreadHere} unread
            </span>
          )}
        </div>
        <div className="alerts-toolbar-right">
          <AttentionControls />
          <button type="button" className="btn small" disabled={!unreadHere} onClick={() => ack()}>
            Acknowledge all
          </button>
          <button type="button" className="btn small ghost" onClick={reload}>
            Refresh
          </button>
        </div>
      </div>
      {(error || liveError) && <div className="banner error">{error || liveError}</div>}
      {view === null ? (
        <div className="card empty-state">Loading alerts…</div>
      ) : view.alerts.length === 0 ? (
        <div className="card empty-state">
          {emptyLead ? (
            <>No alerts today. {emptyLead}</>
          ) : (
            <>
              No alerts {session === "today" ? "yet today" : `on ${view.session}`}. Alerts cover every name with a{" "}
              <Link className="sector-link" to="/">daily setup</Link>
              {view.universe != null ? ` (${view.universe} names right now)` : ""} during the regular session. A watch shows up a
              few minutes after a 15-minute candle pulls back to a rising EMA that is turned on (long setups) or rallies into a
              falling one (short setups that are switched on).
              {today?.last_run?.at && <> Last check {phoenixTime(today.last_run.at)} Phoenix.</>}
            </>
          )}
        </div>
      ) : (
        <>
          <AlertFilterBar filters={filters} onChange={setFilters} ticker={ticker} onTicker={setTicker} shown={shownAlerts.length} total={view.alerts.length} />
          {shownAlerts.length === 0 ? (
            <div className="card empty-state">No alerts match the filters.</div>
          ) : (
            <AlertsTable
              alerts={shownAlerts}
              flashing={flashing}
              onAck={(id) => ack([id])}
              onBought={setMoving}
            />
          )}
        </>
      )}
      {moving && (
        <EntryModal
          title="Move to Positions"
          symbol={moving.symbol}
          initial={{ price: entryPrice(moving), shares: null, side: isShortAlert(moving) ? "short" : "long" }}
          lastPrice={entryPrice(moving)}
          submitLabel="Move to Positions"
          onSubmit={(v) => open(moving.symbol, v)}
          onClose={() => setMoving(null)}
        />
      )}
    </>
  );
}

function HistoryView({ revision }: { revision: number }) {
  const [date, setDate] = useState("");
  const [data, setData] = useState<AlertHistoryPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .alertHistory(date || undefined)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
        if (!date && d.date) setDate(d.date);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [date, revision]);

  const alerts = data?.alerts ?? [];
  const [filters, setFilters] = useAlertFilters();
  const [ticker, setTicker] = useState("");
  const shownAlerts = useMemo(() => filterAlerts(alerts, filters, ticker), [alerts, filters, ticker]);
  return (
    <>
      <div className="table-meta alerts-toolbar">
        <div className="alerts-toolbar-left">
          <label className="muted small" htmlFor="alert-history-date">
            Trading day
          </label>
          <input
            id="alert-history-date"
            className="input date"
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
          {data && (
            <span className="muted small">
              {alerts.length} archived{data.dates.length > 1 ? ` · ${data.dates.length} days kept` : ""}
            </span>
          )}
        </div>
        <span className="muted small">Archived after the close. Read only.</span>
      </div>
      {error && <div className="banner error">{error}</div>}
      {data === null ? (
        <div className="card empty-state">Loading history…</div>
      ) : alerts.length === 0 ? (
        <div className="card empty-state">No archived alerts{data.date ? ` on ${data.date}` : ""}.</div>
      ) : (
        <>
          <AlertFilterBar filters={filters} onChange={setFilters} ticker={ticker} onTicker={setTicker} shown={shownAlerts.length} total={alerts.length} />
          {shownAlerts.length === 0 ? (
            <div className="card empty-state">No archived alerts match the filters.</div>
          ) : (
            <AlertsTable
              alerts={shownAlerts}
              flashing={new Set()}
              onAck={() => undefined}
              onBought={() => undefined}
              readOnly
              sortStorageKey="alertsHistorySort"
            />
          )}
        </>
      )}
    </>
  );
}

function metricSortValue(row: AlertMetricRow, key: string): number | string | null {
  switch (key) {
    case "name":
      return row.name || null;
    case "count":
      return row.count;
    case "filled":
      return row.filled;
    case "fill_rate":
      return row.fill_rate;
    case "closed":
      return row.closed;
    case "win_rate":
      return row.win_rate;
    case "avg_r":
      return row.avg_r;
    case "total_r":
      return row.total_r;
    case "open":
      return row.open;
    default:
      return null;
  }
}

export function MetricsTable({ rows }: { rows: AlertMetricRow[] }) {
  const pct = (v: number | null) => (v == null ? "—" : `${v.toFixed(1)}%`);
  const [stored, setStored] = usePersisted<ColumnSort | null>("alertsMetricsSort", null);
  const sort = normalizeColumnSort(stored, METRIC_SORT_KEYS);
  const ordered = useMemo(() => sortByColumn(rows, sort, metricSortValue), [rows, sort]);
  const header = (key: (typeof METRIC_SORT_KEYS)[number], label: string, className?: string) => (
    <SortableTh
      key={key}
      label={label}
      className={className}
      active={sort?.key === key}
      dir={sort?.dir ?? 1}
      onClick={() => setStored(toggleColumnSort(sort, key))}
    />
  );
  return (
    <div className="card table-card">
      <table className="scan-table metrics-table">
        <thead>
          <tr>
            {header("name", "Daily setup")}
            {header("count", "Alerts", "num")}
            {header("filled", "Filled", "num")}
            {header("fill_rate", "Fill rate", "num")}
            {header("closed", "Closed", "num")}
            {header("win_rate", "Win rate", "num")}
            {header("avg_r", "Avg R", "num")}
            {header("total_r", "Total R", "num")}
            {header("open", "Open", "num")}
          </tr>
        </thead>
        <tbody>
          {ordered.map((r) => (
            <tr key={r.setup} className={r.setup === "All" ? "total-row" : ""}>
              <td>
                {r.side && <span className={`side-chip ${r.side}`}>{r.side === "short" ? "SHORT" : "LONG"}</span>}
                <span className={r.setup === "All" ? "" : "setup-name"}>{r.name}</span>
              </td>
              <td className="num">{r.count}</td>
              <td className="num">{r.filled}</td>
              <td className="num">{pct(r.fill_rate)}</td>
              <td className="num">{r.closed}</td>
              <td className="num">{pct(r.win_rate)}</td>
              <td className={`num ${rTone(r.avg_r)}`}>{fmtR(r.avg_r)}</td>
              <td className={`num ${rTone(r.total_r)}`}>{fmtR(r.total_r)}</td>
              <td className="num">{r.open}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricsView({ revision }: { revision: number }) {
  const [start, setStart] = usePersisted<string>("alertsMetricsStart", "");
  const [end, setEnd] = usePersisted<string>("alertsMetricsEnd", "");
  const [symbol, setSymbol] = usePersisted<string>("alertsMetricsSymbol", "");
  const [data, setData] = useState<AlertMetricsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .alertMetrics({ start: start || undefined, end: end || undefined, symbol: symbol || undefined })
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(String(e)));
  }, [start, end, symbol, revision]);

  return (
    <>
      <div className="table-meta metrics-filters">
        <div className="alerts-toolbar-left">
          <label className="muted small" htmlFor="m-start">From</label>
          <input id="m-start" className="input date" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          <label className="muted small" htmlFor="m-end">To</label>
          <input id="m-end" className="input date" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          <label className="muted small" htmlFor="m-sym">Ticker</label>
          <select id="m-sym" className="input select" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            <option value="">All tickers</option>
            {(data?.symbols ?? []).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {(start || end || symbol) && (
            <button type="button" className="btn small ghost" onClick={() => { setStart(""); setEnd(""); setSymbol(""); }}>
              Clear
            </button>
          )}
        </div>
        <span className="muted small">
          Win rate and R count filled trades that have closed. 1R = entry minus the original stop.
          An alert with several daily setups is counted under each of them. All counts each alert once.
        </span>
      </div>
      {error && <div className="banner error">{error}</div>}
      <MetricsTable rows={data?.rows ?? []} />
    </>
  );
}

export function AlertLiquidityFilters({
  volume,
  atr,
  onVolume,
  onAtr,
}: {
  volume: number;
  atr: AtrRange;
  onVolume: (v: number) => void;
  onAtr: (v: AtrRange) => void;
}) {
  return (
    <div className="filters settings-sliders">
      <div className="filter-row filter-sliders">
        <LogSlider
          label="Min avg $ volume"
          value={volume}
          min={DOLLAR_VOL_RANGE.min}
          max={DOLLAR_VOL_RANGE.max}
          format={(v) => `$${fmtCompact(v)}`}
          onChange={onVolume}
        />
        <AtrSlider value={atr} onChange={onAtr} />
      </div>
      <p className="muted small slider-note">
        Uses each name&apos;s average dollar volume and ATR % from the daily scan, before the name caps.
        Every name, including ones you added to the watchlist yourself, needs an ATR above 3% to be added or to
        alert; the sliders do not apply to names you added.
      </p>
    </div>
  );
}

function SettingsPanel({ onSettings }: { onSettings: (settings: AlertSettings) => void }) {
  const [open, setOpen] = useState(false);
  const [payload, setPayload] = useState<AlertSettingsPayload | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const apply = (p: AlertSettingsPayload) => {
    setPayload(p);
    setDraft(Object.fromEntries(Object.entries(p.settings).map(([k, v]) => [k, String(v)])));
    onSettings(p.settings);
  };
  useEffect(() => {
    if (open && !payload) api.alertSettings().then(apply).catch((e) => setError(String(e)));
  }, [open, payload]);

  const changed = useMemo(() => {
    if (!payload) return {};
    const out: Record<string, number> = {};
    for (const [k, v] of Object.entries(draft)) {
      const n = Number(v);
      if (v.trim() !== "" && Number.isFinite(n) && n !== payload.settings[k]) out[k] = n;
    }
    return out;
  }, [draft, payload]);

  const save = async () => {
    try {
      apply(await api.saveAlertSettings(changed));
      const rules = Object.keys(changed).some((k) => k !== "earnings_window_days" && k !== "auto_archive");
      const warning = "earnings_window_days" in changed;
      const archiveOnly = Object.keys(changed).length === 1 && "auto_archive" in changed;
      setNote(
        archiveOnly
          ? "Saved. Today's alerts move to History after 4:05 PM New York when this is on."
          : rules && warning
            ? "Saved. Setup rules apply from the next check. The earnings warning updates the next time each page loads."
            : warning
              ? "Saved. The earnings warning updates the next time each page loads."
              : "Saved. New values apply from the next check.",
      );
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };
  const reset = async () => {
    apply(await api.resetAlertSettings());
    setNote("Back to the defaults.");
  };

  return (
    <section className="card settings-card">
      <button type="button" className="settings-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>Rule settings</span>
        <span className="muted small">{open ? "Hide" : "Theme gate, EMAs, stop and which short setups"}</span>
      </button>
      {open && payload && (
        <div className="settings-body">
          {SETTING_GROUPS.map((g) => (
            <fieldset key={g.title} className="settings-group">
              <legend>{g.title}</legend>
              {g.title === "Which names" && (
                <AlertLiquidityFilters
                  volume={Number(draft.min_avg_dollar_volume)}
                  atr={normalizeAtrRange([draft.atr_pct_min, draft.atr_pct_max])}
                  onVolume={(v) => setDraft({ ...draft, min_avg_dollar_volume: String(v) })}
                  onAtr={([lo, hi]) => setDraft({ ...draft, atr_pct_min: String(lo), atr_pct_max: String(hi) })}
                />
              )}
              {g.items.map(([key, label, unit]) => (
                <label key={key} className={`setting ${key in changed ? "changed" : ""}`}>
                  <span className="setting-label">{label}</span>
                  <span className="setting-input">
                    <input
                      className="input"
                      type="number"
                      inputMode="decimal"
                      step="any"
                      min={payload.limits[key]?.[0]}
                      max={payload.limits[key]?.[1]}
                      value={draft[key] ?? ""}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                    />
                    {unit && <span className="muted small">{unit}</span>}
                  </span>
                  {payload.defaults[key] !== payload.settings[key] && (
                    <span className="muted small setting-default">default {payload.defaults[key]}</span>
                  )}
                </label>
              ))}
            </fieldset>
          ))}
          <div className="settings-actions">
            <button type="button" className="btn primary" disabled={!Object.keys(changed).length} onClick={save}>
              Save {Object.keys(changed).length ? `(${Object.keys(changed).length})` : ""}
            </button>
            <button type="button" className="btn ghost" onClick={reset}>
              Reset to defaults
            </button>
            {note && <span className="muted small">{note}</span>}
            {error && <span className="red-text small">{error}</span>}
          </div>
        </div>
      )}
    </section>
  );
}

export default function Alerts() {
  const [view, setView] = usePersisted<"alerts" | "history" | "metrics">("alertsView", "alerts");
  const { today, unread, reload } = useAlerts();
  const [now, setNow] = useState(() => new Date());
  const [windowSettings, setWindowSettings] = useState<AlertSettings | undefined>(undefined);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const fired = today?.alerts.length ?? 0;
  const triggered = (today?.alerts ?? []).filter((a) => a.filled).length;
  const top = new Set((today?.alerts ?? []).filter((a) => a.top).map((a) => a.symbol)).size;
  const day = useMemo(() => alertDayStatus(now, windowSettings), [now, windowSettings]);

  useEffect(() => {
    api.alertSettings().then((p) => setWindowSettings(p.settings)).catch(() => undefined);
  }, []);
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  const clearHistory = async () => {
    setClearing(true);
    setClearError(null);
    try {
      await api.clearAlertHistory();
      setRevision((n) => n + 1);
      reload();
      setConfirmClear(false);
    } catch (e) {
      setClearError(e instanceof Error ? e.message : String(e));
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="page alerts-page">
      <section className="hero">
        <div>
          <h1>Alerts</h1>
          <p className="muted">
            Longs in a top-quartile theme; shorts via mapped inverse ETFs when EMA Crossback Short is on.
            Default entry is a 15-minute close back above the 6 EMA (buy that candle&apos;s high + 1c, stop at its low − 1c).
            The rising-120 pullback remains selectable. An order wider than 1% is skipped. Times are Phoenix.
          </p>
          <AlertDayBanner status={day} />
        </div>
        <div className="stat-cards">
          <div className="stat-card">
            <span className="stat-value">{fired}</span>
            <span className="stat-label">today</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{triggered}</span>
            <span className="stat-label">triggered</span>
          </div>
          <div className="stat-card">
            <span className={`stat-value ${unread ? "accent-text" : ""}`}>{unread}</span>
            <span className="stat-label">unread</span>
          </div>
          <div className="stat-card">
            <span className="stat-value">{top}</span>
            <span className="stat-label">top names</span>
          </div>
        </div>
      </section>
      <div className="alerts-tabs">
        <div className="seg" role="tablist">
          <button type="button" role="tab" aria-selected={view === "alerts"} className={view === "alerts" ? "active" : ""} onClick={() => setView("alerts")}>
            Alerts
          </button>
          <button type="button" role="tab" aria-selected={view === "history"} className={view === "history" ? "active" : ""} onClick={() => setView("history")}>
            History
          </button>
          <button type="button" role="tab" aria-selected={view === "metrics"} className={view === "metrics" ? "active" : ""} onClick={() => setView("metrics")}>
            Metrics by setup
          </button>
        </div>
        <button type="button" className="btn small danger" onClick={() => { setClearError(null); setConfirmClear(true); }}>
          Clear history
        </button>
      </div>
      {confirmClear && (
        <Modal title="Clear alert history?" onClose={() => { if (!clearing) setConfirmClear(false); }} wide>
          <p className="confirm-text">
            This deletes every alert outcome: today's live alerts, including ones still watching or filled, and every
            archived day. Metrics go back to empty. Your watchlist, positions, and rule settings stay.
          </p>
          {clearError && <p className="red-text small">{clearError}</p>}
          <div className="modal-actions">
            <button type="button" className="btn ghost" disabled={clearing} onClick={() => setConfirmClear(false)}>
              Cancel
            </button>
            <button type="button" className="btn danger" disabled={clearing} onClick={clearHistory}>
              {clearing ? "Clearing…" : "Clear history"}
            </button>
          </div>
        </Modal>
      )}
      {view === "history" ? <HistoryView revision={revision} /> : view === "alerts" ? <AlertsView day={day} /> : <MetricsView revision={revision} />}
      <SettingsPanel onSettings={setWindowSettings} />
    </div>
  );
}
