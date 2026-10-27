import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  type AlertHistoryPayload,
  type AlertMetricsPayload,
  type AlertSettings,
  type AlertSettingsPayload,
  type AlertsPayload,
  type Ema5m,
  type TradeAlert,
} from "../api";
import {
  SETTING_GROUPS,
  STATUS_LABEL,
  alertDayStatus,
  ema360Text,
  ema360Title,
  ema360Tone,
  fmtR,
  phoenixTime,
  rTone,
  riskPerShare,
  statusTone,
  stopPct,
  todayEmptyLead,
  type AlertDayStatus,
} from "../alerts";
import { useAlerts } from "../components/AlertsCenter";
import { EmaPill } from "../components/ListIntradayColumns";
import { EntryModal } from "../components/Modal";
import { usePositions } from "../components/Positions";
import { ScorePill } from "../components/ScoreBreakdown";
import { EarningsIcon } from "../components/EarningsIcon";
import { TickerLogo } from "../components/TickerLogo";
import { usePersisted } from "../persist";

const SETUP_NAMES: Record<string, string> = {
  A: "Opening-bar breakout",
  B: "Opening flush then reclaim",
  C: "Opening-drive continuation",
  D: "Pullback to rising 20 EMA",
  E: "Gap-down V-reversal",
  F: "Midday squeeze",
};

/** One-line trigger rule, shown on hover over the setup column. */
const SETUP_RULES: Record<string, string> = {
  A: "Opening bar closes in the top 30% and over the 6 and 20 EMAs.",
  B: "After a dip under the open or prior close, the first green close over the bunched 6/20/50.",
  C: "After a strong open, a bar closes over the opening high, or tight bars hold over the 6 EMA.",
  D: "After a pullback to the rising 20 EMA, a green bar closes back over the 6.",
  E: "Gap under the prior close, or a low under the 20 and 50, then a higher low and the first close back over the 20.",
  F: "After the 6/20/50 stay flat and bunched, a full green bar breaks out on heavy volume.",
};

const money = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));

/** Shown when the lists poll has no 5-minute EMA for this symbol (it is on neither list). */
const emaMissing = (period: 6 | 20) =>
  `No live 5-minute ${period} EMA (only names on the watchlist or in positions are polled)`;

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

function outcomeText(a: TradeAlert): string {
  if (a.status === "pending") return "Waiting for the buy stop";
  if (a.status === "expired") return a.exit_reason === "max_attempts" ? "Expired: 2 attempts already" : "Not triggered in time";
  if (a.status === "cancelled") return "Closed under the setup low";
  const parts = [`Filled ${money(a.fill_price)} at ${phoenixTime(a.fill_at)}`];
  if (a.breakeven_at) parts.push(`stop to break-even ${phoenixTime(a.breakeven_at)}`);
  if (a.exit_price != null) {
    const why = a.exit_reason === "close_under_20ema" ? "close under 20 EMA" : a.exit_reason === "session_end" ? "session end" : "stop";
    parts.push(`out ${money(a.exit_price)} at ${phoenixTime(a.exit_at)} (${why})`);
  }
  return parts.join(", ");
}

export function AlertsTable({
  alerts,
  flashing,
  onAck,
  onBought,
  ema5m,
  readOnly = false,
}: {
  alerts: TradeAlert[];
  flashing: Set<number>;
  onAck: (id: number) => void;
  onBought: (alert: TradeAlert) => void;
  /** Live 5-minute EMA by symbol. Missing or null renders a dash. */
  ema5m?: Record<string, Ema5m | null>;
  /** History rows keep the same columns and do not acknowledge or record a buy. */
  readOnly?: boolean;
}) {
  return (
    <div className="card table-card">
      <table className="scan-table alerts-table">
        <thead>
          <tr>
            <th>Fired</th>
            <th>Ticker</th>
            <th className="num">Score</th>
            <th>Setup</th>
            <th className="ema-col" title="Live price versus the 6 EMA on the 5-minute chart">
              6 EMA (5m)
            </th>
            <th className="ema-col" title="Live price versus the 20 EMA on the 5-minute chart">
              20 EMA (5m)
            </th>
            <th className="num">Trigger</th>
            <th className="num">Stop</th>
            <th className="num">Stop %</th>
            <th className="num">Risk / sh</th>
            <th className="num" title="Setup bar close vs the 5-minute EMA 360 (about the 1-hour EMA 30)">vs EMA360</th>
            <th>Status</th>
            <th className="num">High</th>
            <th className="num">R</th>
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
              <td>
                <span className="setup-hover" title={SETUP_RULES[a.setup]}>
                  <span className="setup-letter">{a.setup}</span>
                  <span className="muted small setup-name">{SETUP_NAMES[a.setup]}</span>
                </span>
              </td>
              <td className="ema-col">
                <EmaPill em={ema5m?.[a.symbol]} period={6} missing={emaMissing(6)} />
              </td>
              <td className="ema-col">
                <EmaPill em={ema5m?.[a.symbol]} period={20} missing={emaMissing(20)} />
              </td>
              <td className="num">{money(a.trigger_price)}</td>
              <td className="num">{money(a.stop_price)}</td>
              <td className="num">{stopPct(a).toFixed(2)}%</td>
              <td className="num">{money(riskPerShare(a))}</td>
              <td className={`num ${ema360Tone(a)}`} title={ema360Title(a)}>
                {ema360Text(a)}
              </td>
              <td>
                <StatusPill a={a} />
              </td>
              <td className="num">{money(a.high_reached)}</td>
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
                    Bought →
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
            <span className="setup-letter">{w.setup}</span>
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
              No alerts {session === "today" ? "yet today" : `on ${view.session}`}. Alerts cover the{" "}
              <Link className="sector-link" to="/watchlist">Watchlist</Link> ({view.watchlist.length} names) during the regular session and
              show up about a minute after each 5-minute bar closes.
              {today?.last_run?.at && <> Last check {phoenixTime(today.last_run.at)} Phoenix.</>}
            </>
          )}
        </div>
      ) : (
        <AlertsTable
          alerts={view.alerts}
          flashing={flashing}
          ema5m={view.ema5m}
          onAck={(id) => ack([id])}
          onBought={setMoving}
        />
      )}
      {moving && (
        <EntryModal
          title="Move to Positions"
          symbol={moving.symbol}
          initial={{ price: entryPrice(moving), shares: null }}
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
        <AlertsTable
          alerts={alerts}
          flashing={new Set()}
          ema5m={data.ema5m}
          onAck={() => undefined}
          onBought={() => undefined}
          readOnly
        />
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
                    {r.setup !== "All" && <span className="setup-letter">{r.setup}</span>}
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
            ? "Saved. Setup rules apply from the next 5-minute check. The earnings warning updates the next time each page loads."
            : warning
              ? "Saved. The earnings warning updates the next time each page loads."
              : "Saved. New values apply from the next 5-minute check.",
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
        <span className="muted small">{open ? "Hide" : "Adjust the setup rules and the earnings warning"}</span>
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
            Setups A to F on the 5-minute chart for your watchlist, regular session only. Each one is a buy stop 1c over the setup
            bar with a stop 1c under it, tracked until it fills, stops, exits or expires. Times are Phoenix.
          </p>
          <AlertDayBanner status={day} />
        </div>
        <div className="stat-cards">
          <div className="stat-card">
            <span className="stat-value">{fired}</span>
            <span className="stat-label">today</span>
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
      </div>
      {view === "history" ? <HistoryView /> : view === "alerts" ? <AlertsView day={day} /> : <MetricsView />}
      <SettingsPanel onSettings={setWindowSettings} />
    </div>
  );
}
