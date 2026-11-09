import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type AlertHistoryPayload,
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
  SETUP_RULES,
  STATUS_LABEL,
  alertDayStatus,
  isShortSetup,
  setupPeriod,
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
import { EntryModal } from "../components/Modal";
import { usePositions } from "../components/Positions";
import { ScorePill } from "../components/ScoreBreakdown";
import { EarningsIcon } from "../components/EarningsIcon";
import { TickerLogo } from "../components/TickerLogo";
import { INTRADAY_EMA_COLORS } from "../intradayChart";
import { usePersisted } from "../persist";
import { fmtRs } from "../leadership";
import { RangeSlider } from "../components/RangeSlider";

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

function outcomeText(a: TradeAlert): string {
  const short = isShortSetup(a.setup);
  const ema = `${setupPeriod(a.setup)} EMA`;
  if (a.status === "pending") {
    return short
      ? `Watching: trigger under ${money(a.setup_low)} (last 15-min low)`
      : `Watching: trigger over ${money(a.setup_high)} (last 15-min high)`;
  }
  if (a.status === "expired") {
    if (a.exit_reason === "max_attempts") return "Expired: 2 attempts already";
    if (a.exit_reason === "session_end") return "Not triggered by the close";
    return "Not triggered in time";
  }
  if (a.status === "cancelled") return `Closed ${short ? "over" : "under"} the ${ema} before triggering`;
  const parts = [`Filled ${money(a.fill_price)} at ${phoenixTime(a.fill_at)}`];
  if (a.breakeven_at) parts.push(`stop to break-even ${phoenixTime(a.breakeven_at)}`);
  if (a.exit_price != null) {
    const why =
      a.exit_reason === "close_under_ma"
        ? `close under ${ema}`
        : a.exit_reason === "close_over_ma"
          ? `close over ${ema}`
          : a.exit_reason === "session_end"
            ? "session end"
            : "stop";
    parts.push(`out ${money(a.exit_price)} at ${phoenixTime(a.exit_at)} (${why})`);
  }
  return parts.join(", ");
}

export function AlertsTable({
  alerts,
  flashing,
  onAck,
  onBought,
  readOnly = false,
}: {
  alerts: TradeAlert[];
  flashing: Set<number>;
  onAck: (id: number) => void;
  onBought: (alert: TradeAlert) => void;
  /** History rows keep the same columns and do not acknowledge or record a buy. */
  readOnly?: boolean;
}) {
  return (
    <div className="card table-card">
      <table className="scan-table alerts-table">
        <thead>
          <tr>
            <th title="When the 15-minute candle that touched the EMA closed">Watch</th>
            <th>Ticker</th>
            <th className="num">Score</th>
            <th className="num" title="Relative strength percentile, as on the Stock Scanner">RS</th>
            <th>Side</th>
            <th title="The daily setup(s) that put this name on the alert list">Daily setup</th>
            <th title="Industry, and its rank among stock industries by median RS (1 = strongest)">Industry</th>
            <th>Entry</th>
            <th className="num" title="The EMA's value on the touch candle">EMA</th>
            <th className="num" title="Previous 15-minute candle high + 1c (short: low - 1c)">Trigger</th>
            <th className="num">Stop</th>
            <th className="num">Stop %</th>
            <th className="num">Risk / sh</th>
            <th>Status</th>
            <th className="num" title="Best price since the fill: the high (short: the low)">Best</th>
            <th className="num" title="Open trades (triggered, not stopped or exited): R at the last price">Open R</th>
            <th className="num" title="Closed trades: R at the exit">R</th>
            <th className="outcome-cell">What happened</th>
            <th className="bought-col" aria-label="Bought" />
            <th className="actions-col" aria-label="Acknowledge" />
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
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
                <span className={`side-chip ${isShortSetup(a.setup) ? "short" : "long"}`}>
                  {isShortSetup(a.setup) ? "SHORT" : "LONG"}
                </span>
              </td>
              <td className="daily-setup-cell">
                {a.details?.daily_setups?.length ? a.details.daily_setups.join(", ") : <span className="muted">—</span>}
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
              <td className="muted small outcome-cell">{outcomeText(a)}</td>
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
                    {isShortSetup(a.setup) ? "Shorted →" : "Bought →"}
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
              few minutes after a 15-minute candle pulls back to a rising 120, 240 or 480 EMA (long setups) or rallies into a
              falling one (short setups).
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
          initial={{ price: entryPrice(moving), shares: null, side: isShortSetup(moving.setup) ? "short" : "long" }}
          lastPrice={entryPrice(moving)}
          submitLabel="Move to Positions"
          onSubmit={(v) => open(moving.symbol, v)}
          onClose={() => setMoving(null)}
        />
      )}
    </>
  );
}

function HistoryView() {
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
  }, [date]);

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
            />
          )}
        </>
      )}
    </>
  );
}

function MetricsView() {
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
  }, [start, end, symbol]);

  const pct = (v: number | null) => (v == null ? "—" : `${v.toFixed(1)}%`);
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
        <span className="muted small">Win rate and R count filled trades that have closed. 1R = entry minus the original stop.</span>
      </div>
      {error && <div className="banner error">{error}</div>}
      <div className="card table-card">
        <table className="scan-table metrics-table">
          <thead>
            <tr>
              <th>Setup</th>
              <th className="num">Alerts</th>
              <th className="num">Filled</th>
              <th className="num">Fill rate</th>
              <th className="num">Closed</th>
              <th className="num">Win rate</th>
              <th className="num">Avg R</th>
              <th className="num">Total R</th>
              <th className="num">Open</th>
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((r) => (
              <tr key={r.setup} className={r.setup === "All" ? "total-row" : ""}>
                <td>
                  <span className={SETUP_RULES[r.setup] ? "setup-hover" : undefined} title={SETUP_RULES[r.setup]}>
                    {r.setup !== "All" && (
                      <span className="setup-letter">
                        <EmaDot setup={r.setup} />
                        {isShortSetup(r.setup) && <span className="side-chip short">SHORT</span>}
                        {setupPeriod(r.setup)}
                      </span>
                    )}
                    <span className={r.setup === "All" ? "" : "setup-name"}>{r.name}</span>
                  </span>
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
    </>
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
        <span className="muted small">{open ? "Hide" : "Adjust the score cut, the EMAs and the earnings warning"}</span>
      </button>
      {open && payload && (
        <div className="settings-body">
          {SETTING_GROUPS.map((g) => (
            <fieldset key={g.title} className="settings-group">
              <legend>{g.title}</legend>
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
  const { today, unread } = useAlerts();
  const [now, setNow] = useState(() => new Date());
  const [windowSettings, setWindowSettings] = useState<AlertSettings | undefined>(undefined);
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

  return (
    <div className="page alerts-page">
      <section className="hero">
        <div>
          <h1>Alerts</h1>
          <p className="muted">
            Entries for any daily setup, timed on the 15-minute chart: a long daily setup pulling back to a rising 120 (red),
            240 (yellow) or 480 (blue) EMA, or a short daily setup rallying up into a falling one (resistance). Regular session
            only. When a candle touches one of them and holds, you get a watch alert. A long triggers when price trades 1c over
            the previous 15-minute candle's high, with a stop 1c under the pullback low (a short: 1c under the low, stop 1c
            over the rally high), and is tracked until it fills, stops, exits or expires. Times are Phoenix.
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
            Metrics by EMA
          </button>
        </div>
      </div>
      {view === "history" ? <HistoryView /> : view === "alerts" ? <AlertsView day={day} /> : <MetricsView />}
      <SettingsPanel onSettings={setWindowSettings} />
    </div>
  );
}
