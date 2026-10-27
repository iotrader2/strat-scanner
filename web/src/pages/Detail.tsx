import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, fmtMoney, fmtPct, type ChartCandle, type IntradayChartData, type ScanRow, type Tf } from "../api";
import { triggerChip } from "../setupFilter";
import { DETAIL_CHART_BUTTONS, DETAIL_TF_KEY, isDetailChart, type DetailChart, usePersisted } from "../persist";
import { LoadingIndicator } from "../components/Loading";
import { NO_SETUP_LABEL } from "../watchlist";
import { AddedChip, ScorePill, TfBadge } from "../components/Badges";
import { TickerLogo } from "../components/TickerLogo";
import { fmtPerf, perfClass, PERF_PERIODS } from "../perf";
import { scanThemeHref } from "../themes";
import { EarningsIcon } from "../components/EarningsIcon";
import { BreakdownTable } from "../components/ScoreBreakdown";
import { WatchButton } from "../components/Watch";
import { CandleChart } from "../components/CandleChart";
import { IntradayChart } from "../components/IntradayChart";

const CHART_HEIGHT = 600;

export default function Detail({ version }: { version: string | null }) {
  const { symbol = "" } = useParams();
  const [data, setData] = useState<{ row: ScanRow; charts: Record<Tf, ChartCandle[]> } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [intraday, setIntraday] = useState<IntradayChartData | null>(null);
  const [intradayError, setIntradayError] = useState<string | null>(null);
  const [storedTf, setTf] = usePersisted<DetailChart | null>(DETAIL_TF_KEY, null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .symbol(symbol)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [symbol, version]);

  const row = data?.row;
  // Saved choice wins. Otherwise the row's trigger timeframe, then Weekly. 5min is never the default.
  const chart: DetailChart | null = isDetailChart(storedTf) ? storedTf : row ? (row.trigger_tf ?? "W") : null;
  // Once the row is in, chart is a real selection. The fallback only satisfies the type before that.
  const view: DetailChart = chart ?? "W";

  useEffect(() => {
    if (chart !== "5m") return;
    let cancelled = false;
    setIntraday(null);
    setIntradayError(null);
    api
      .bars5m(symbol)
      .then((bars) => {
        if (!cancelled) setIntraday(bars);
      })
      .catch((e) => {
        if (!cancelled) setIntradayError(e instanceof ApiError ? e.message : "5-minute bars are unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [chart, symbol, version]);

  if (error) return <div className="page"><div className="banner error">{error}</div></div>;
  if (!data || !row)
    return (
      <div className="page" aria-busy="true">
        <Link to="/" className="back">← Stock Scanner</Link>
        <section className="detail-head card skeleton-card">
          <div>
            <LoadingIndicator label={`Loading ${symbol?.toUpperCase() ?? ""}…`} className="big-loading" />
            <span className="skeleton-bar wide" />
          </div>
        </section>
        <div className="detail-grid" aria-hidden="true">
          <section className="card chart-card skeleton-card">
            <div className="skeleton-row">
              <span className="skeleton-bar pill" />
              <span className="skeleton-bar pill" />
              <span className="skeleton-bar pill" />
              <span className="skeleton-bar pill" />
            </div>
            <div className="skeleton-chart" style={{ height: 600 }} />
          </section>
          <aside className="side">
            {[0, 1, 2].map((i) => (
              <div key={i} className="card skeleton-card">
                <span className="skeleton-bar mid" />
                <span className="skeleton-bar wide" />
                <span className="skeleton-bar" />
                <span className="skeleton-bar wide" />
              </div>
            ))}
          </aside>
        </div>
      </div>
    );

  return (
    <div className="page">
      <Link to="/" className="back">← Stock Scanner</Link>
      <section className="detail-head card">
        <div>
          <div className="detail-symbol">
            <TickerLogo symbol={row.symbol} size={26} />
            {row.symbol}
            <EarningsIcon earnings={row.earnings} />
            <span className="muted detail-name">{row.name}</span>
            {row.in_universe === false && <AddedChip />}
            <WatchButton symbol={row.symbol} labelled />
          </div>
          <div className="muted small">
            {row.theme && row.theme_name ? (
              <Link className="sector-link" to={scanThemeHref(row.theme)} title="Scan this theme">{row.theme_name}</Link>
            ) : (
              <span>{row.kind === "etf" ? "ETF" : "No theme"}</span>
            )}
            {(row.secondary_themes?.length ?? 0) > 0 && (
              <>
                {" "}· also{" "}
                {row.secondary_themes!.map((t, i) => (
                  <span key={t}>
                    {i > 0 && ", "}
                    <Link className="sector-link" to={scanThemeHref(t)}>{row.secondary_theme_names?.[i] ?? t}</Link>
                  </span>
                ))}
              </>
            )}
            {row.sector && <> · {row.sector}</>}
            {row.industry && <> · {row.industry}</>}
            {" "}· as of {row.as_of}
          </div>
        </div>
        <div className="detail-price">
          <span className="big">{row.price.toFixed(2)}</span>
          <span className={row.change_pct >= 0 ? "green-text" : "red-text"}>{fmtPct(row.change_pct, 2)}</span>
        </div>
        <div className="detail-kpis">
          <div><span className="kpi-label">Score</span><ScorePill score={row.score} row={row} /></div>
          <div><span className="kpi-label">Avg $vol</span><span className="kpi">{fmtMoney(row.avg_dollar_volume)}</span></div>
          {PERF_PERIODS.map((p) => (
            <div key={p.key}>
              <span className="kpi-label">{p.label}</span>
              <span className={`kpi ${perfClass(row.perf?.[p.key])}`}>{fmtPerf(row.perf?.[p.key])}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="detail-grid">
        <section className="card chart-card">
          <div className="chart-toolbar">
            <div className="seg">
              {DETAIL_CHART_BUTTONS.map((button) => (
                <button key={button.id} className={button.id === view ? "active" : ""} onClick={() => setTf(button.id)}>
                  {button.label}
                </button>
              ))}
            </div>
            {view !== "5m" && <span className="muted small">H = hammer · I = inside bar</span>}
          </div>
          {view === "5m" ? (
            <>
              {intradayError && <p className="muted small">{intradayError}</p>}
              {!intraday && !intradayError && (
                <div aria-busy="true">
                  <LoadingIndicator label={`Loading 5-minute ${row.symbol}`} />
                  <div className="skeleton-chart" style={{ height: CHART_HEIGHT }} />
                </div>
              )}
              {intraday && (
                <IntradayChart
                  bars={intraday.bars}
                  height={CHART_HEIGHT}
                  displaySessions={intraday.display_sessions}
                  seedSessions={intraday.seed_sessions}
                />
              )}
            </>
          ) : (
            <CandleChart candles={data.charts[view]} height={CHART_HEIGHT} visibleBars={view === "M" ? 60 : 70} />
          )}
        </section>

        <aside className="side">
          <div className="card">
            <h3>Setup</h3>
            <p className="setup big-setup">{row.has_setup && row.setup ? row.setup : <span className="no-setup">{NO_SETUP_LABEL}</span>}</p>
            <ul className="reasons">
              {row.reason
                .split(" · ")
                .filter((r) => row.has_setup || !r.startsWith("No weekly"))
                .map((r) => <li key={r}>{r}</li>)}
            </ul>
          </div>
          <div className="card">
            <h3>Score breakdown</h3>
            <BreakdownTable row={row} showDetail />
          </div>
          <div className="card">
            <h3>Timeframes</h3>
            <table className="tf-table">
              <thead>
                <tr><th /><th>Strat</th><th className="num">Open</th><th className="num">High</th><th className="num">Low</th><th>Flags</th></tr>
              </thead>
              <tbody>
                {(["D", "W", "M"] as Tf[]).map((t) => {
                  const st = row.tf[t];
                  return (
                    <tr key={t} className={t === view ? "active" : ""} onClick={() => setTf(t)}>
                      <td><TfBadge tf={t} state={st} /></td>
                      <td className="muted small">{st?.prev_strat ?? "–"} → {st?.strat ?? "–"}</td>
                      <td className="num">{st?.open.toFixed(2)}</td>
                      <td className="num">{st?.high.toFixed(2)}</td>
                      <td className="num">{st?.low.toFixed(2)}</td>
                      <td className="small">
                        {st?.inside && <span className="flag">inside bar</span>}
                        {st?.hammer && <span className="flag hammer">hammer</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h3>Weekly setups</h3>
            {row.setups && row.setups.length > 0 ? (
              <ul className="setup-list">
                {row.setups.map((s, i) => (
                  <li key={i}>
                    <span className="tf-tag">{s.tf}</span>
                    <span className="grow">
                      {s.label}
                      {triggerChip(s) && (
                        <span className="trig-chip" title={triggerChip(s)?.title}>
                          {triggerChip(s)?.label}
                        </span>
                      )}
                    </span>
                    <span className="accent-text">{s.trigger.toFixed(2)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">No weekly inside bar, hammer or bullish combo right now.</p>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
