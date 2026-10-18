import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import {
  CHECK_INS,
  SINGLE_HORIZONS,
  SINGLE_METRICS,
  SINGLE_RULES,
  STRAT_METRICS,
  bestSentence,
  crossNote,
  crossSentence,
  displayTime,
  reclaimNote,
  reclaimSentence,
  entryNote,
  orderedRows,
  outcomeLine,
  realizedR,
  returnTone,
  shownRank,
  signedPct,
  signedR,
  stratNote,
  stratSentence,
  type MorningMode,
  type MorningRow,
  type MorningWeek,
  type SingleHorizon,
  type StratHorizon,
  type WindowStat,
} from "../morning";

const COMPARE = ["eod", "d1", "d2", "d3", "d4", "d5"] as const;
const COMPARE_LABEL: Record<(typeof COMPARE)[number], string> = {
  eod: "EOD",
  d1: "+1d",
  d2: "+2d",
  d3: "+3d",
  d4: "+4d",
  d5: "+5d",
};

function Shield() {
  return (
    <svg className="pill-shield" viewBox="0 0 16 16" aria-hidden="true">
      <path fill="currentColor" d="M8 1.3 2.6 3.3v4.1c0 3.2 2.2 5.5 5.4 6.5 3.2-1 5.4-3.3 5.4-6.5V3.3L8 1.3Z" />
    </svg>
  );
}

function logoHue(symbol: string): number {
  let hue = 0;
  for (const ch of symbol) hue = (hue * 33 + ch.charCodeAt(0)) % 360;
  return hue;
}

function TickerLogo({ symbol }: { symbol: string }) {
  const [failed, setFailed] = useState(false);
  const loaded = useRef(false);
  const letter = symbol.replace(/[^A-Za-z0-9]/g, "").charAt(0) || "?";
  useEffect(() => {
    loaded.current = false;
    const timer = window.setTimeout(() => {
      if (!loaded.current) setFailed(true);
    }, 2000);
    return () => window.clearTimeout(timer);
  }, [symbol]);
  if (failed) {
    return (
      <span className="ticker-logo fallback" style={{ background: `hsl(${logoHue(symbol)} 32% 32%)` }} aria-hidden="true">
        {letter}
      </span>
    );
  }
  return (
    <img
      className="ticker-logo"
      src={`https://logo.synthfinance.com/ticker/${encodeURIComponent(symbol)}`}
      alt=""
      width={22}
      height={22}
      onLoad={() => {
        loaded.current = true;
      }}
      onError={() => setFailed(true)}
    />
  );
}

function WeekRow({ row, mode }: { row: MorningRow; mode: MorningMode }) {
  const outcome = mode === "leaders" ? undefined : row.windows[mode];
  const ret = realizedR(outcome, "d3_ret");
  const rank = shownRank(row, mode);
  const skipped = mode !== "leaders" && outcome?.qualified === 0;
  const cross = outcome?.cross_time;
  return (
    <div className={`week-row${skipped ? " is-skipped" : ""}`}>
      <span className="week-rank">{rank ?? "–"}</span>
      <TickerLogo symbol={row.symbol} />
      <Link className="week-sym" to={`/stock/${encodeURIComponent(row.symbol)}`}>
        {row.symbol}
      </Link>
      {mode !== "leaders" && cross && <span className="week-cross">{displayTime(cross)}</span>}
      {mode !== "leaders" && skipped && <span className="week-skip">skipped</span>}
      {mode !== "leaders" && !skipped && (
        <span className={`week-ret ${returnTone(ret)}`} title={outcomeLine(outcome)}>
          {signedR(ret)}
        </span>
      )}
      <span className="score-pill" title={`${row.name} · leadership ${row.score.toFixed(1)} as of ${row.as_of}`}>
        <Shield />
        {Math.round(row.score)}
      </span>
      {mode !== "leaders" && <div className="week-tip">{outcomeLine(outcome)}</div>}
    </div>
  );
}

function formatSingle(
  horizon: SingleHorizon | StratHorizon | undefined,
  key: keyof SingleHorizon | keyof StratHorizon,
  kind: "count" | "pct" | "r" | "rate" | "r1",
): string {
  const value = horizon ? (horizon as unknown as Record<string, number | null | undefined>)[key] : undefined;
  if (value == null) return "—";
  if (kind === "count") return String(value);
  if (kind === "rate") return `${Math.round(Number(value) * 100)}%`;
  if (kind === "pct") return signedPct(Number(value), 2);
  if (kind === "r1") return signedR(Number(value), 1);
  return signedR(Number(value), 2);
}

function SingleEntryTable({ stats }: { stats: MorningWeek["stats"]["single_entry"] }) {
  if (!stats?.order?.length) return null;
  return (
    <section className="card single-entry" aria-label="Single entry study">
      <div className="compare-head">
        <h2>Single entry, low of day</h2>
        <p className="muted small">{stats.definition}</p>
      </div>
      <div className="single-grid">
        {SINGLE_RULES.map((rule) => (
          <div className="single-rule" key={rule.title}>
            <h3>{rule.title}</h3>
            {rule.books.map((id) => (
              <p className="muted small" key={id}>{entryNote(stats.books[id])}</p>
            ))}
            <div className="table-card">
              <table className="scan-table morning-table single-table">
                <thead>
                  <tr>
                    <th> </th>
                    {rule.books.map((id) => (
                      <th className="num" key={id}>{stats.books[id]?.label ?? id}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {SINGLE_HORIZONS.map((horizon) => (
                    <Fragment key={horizon}>
                      <tr className="single-horizon">
                        <th colSpan={1 + rule.books.length}>{COMPARE_LABEL[horizon]}</th>
                      </tr>
                      {SINGLE_METRICS.map((metric) => (
                        <tr key={`${horizon}-${metric.key}`}>
                          <th scope="row">{metric.label}</th>
                          {rule.books.map((id) => {
                            const block = stats.books[id]?.horizons[horizon];
                            const raw = block?.[metric.key];
                            const tone = metric.kind === "pct" || metric.kind === "r" || metric.kind === "r1" ? returnTone(typeof raw === "number" ? raw : null) : "";
                            return (
                              <td className={`num ${tone}`} key={id}>
                                {formatSingle(block, metric.key, metric.kind)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function StatCells({
  stat,
  stopped,
  qualified,
}: {
  stat: WindowStat | undefined;
  stopped: boolean;
  qualified: number | null;
}) {
  const qualifiedCell = <td className="num">{qualified == null ? "—" : qualified.toFixed(1)}</td>;
  const blank = (
    <>
      <td className="num">—</td>
      <td className="num">—</td>
      {qualifiedCell}
      {COMPARE.map((h) => (
        <td key={h} className="num">—</td>
      ))}
      <td className="num">—</td>
      <td className="num">—</td>
      <td className="num">—</td>
      <td className="num">—</td>
      <td className="num">—</td>
      <td className="num">—</td>
    </>
  );
  if (!stat) return blank;
  const primary = stat.horizons.d3?.n_days ? stat.horizons.d3 : stat.horizons.eod;
  if (!primary) return blank;
  return (
    <>
      <td className="num">{primary.n_days || "—"}</td>
      <td className="num">{primary.n_trades || "—"}</td>
      {qualifiedCell}
      {COMPARE.map((h) => {
        const value = stat.horizons[h]?.avg;
        return (
          <td key={h} className={`num ${returnTone(value)}`}>
            {signedR(value, 2)}
          </td>
        );
      })}
      <td className="num">{primary.win_rate == null ? "—" : `${Math.round(primary.win_rate * 100)}%`}</td>
      <td className="num">{!stopped || primary.stop_hit_rate == null ? "—" : `${Math.round(primary.stop_hit_rate * 100)}%`}</td>
      <td className="num">{!stopped || primary.gap_count == null ? "—" : primary.gap_count}</td>
      <td className={`num ${returnTone(primary.total_r)}`}>{signedR(primary.total_r, 1)}</td>
      <td className={`num ${returnTone(primary.expectancy)}`}>{signedR(primary.expectancy, 2)}</td>
      <td className={`num ${returnTone(primary.avg_mfe)}`}>{signedR(primary.avg_mfe, 2)}</td>
    </>
  );
}

export default function Morning() {
  const [week, setWeek] = useState<string | null>(null);
  const [mode, setMode] = useState<MorningMode>("leaders");
  const [data, setData] = useState<MorningWeek | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancel = false;
    api
      .morning(week)
      .then((body) => {
        if (!cancel) {
          setData(body);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancel) setError(String(e));
      });
    return () => {
      cancel = true;
    };
  }, [week]);

  const stats = data?.stats;
  const best = stats?.best ?? null;
  const sentence = bestSentence(best);

  return (
    <div className="page morning-page">
      <header className="hero">
        <div>
          <h1>Morning Leaders</h1>
          <p>Do not watch stocks every minute. Check the leaders at one of these times.</p>
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}

      <section className="best-panel card" aria-label="Best time to buy leaders">
        <div className="best-kicker">Best time to buy leaders</div>
        {best && sentence ? (
          <>
            <div className="best-time">{displayTime(best.window)}</div>
            <p>{sentence}</p>
            <p className="muted small">
              {signedR(best.vs_qqq, 2)} versus QQQ from the same minute
              {best.avg_mfe != null && ` · MFE ${signedR(best.avg_mfe, 2)}`}
              {best.avg_qualified != null && ` · ${best.avg_qualified.toFixed(1)} names above the 20 RMA on average`}
              {" · "}
              {best.n_days} mornings, {best.n_trades} fills. Names in one morning move together.
            </p>
          </>
        ) : (
          <p className="muted">A few completed mornings will show which check-in has worked.</p>
        )}
      </section>

      <div className="interval-tabs" role="tablist" aria-label="Check-in time">
        <button type="button" role="tab" aria-selected={mode === "leaders"} className={mode === "leaders" ? "active" : ""} onClick={() => setMode("leaders")}>
          Leaders
        </button>
        {CHECK_INS.map((id) => (
          <button key={id} type="button" role="tab" aria-selected={mode === id} className={mode === id ? "active" : ""} onClick={() => setMode(id)}>
            {displayTime(id)}
          </button>
        ))}
      </div>
      <p className="interval-note muted small">
        {mode === "leaders"
          ? "Top 10 at the prior close. The pill is the leadership score."
          : `Bought once a 5-minute bar closes above the 20 RMA. Earliest cross first. The time is that cross; the number is the +3 day result in R. A 1% stop books −1R. Names still under the average are skipped.`}
      </p>

      <section className="week-card card">
        <div className="week-head">
          <div className="week-title-row">
            <button type="button" className="week-arrow" onClick={() => data?.prev && setWeek(data.prev)} disabled={!data?.prev} aria-label="Previous week">
              ‹
            </button>
            <h2>{data?.title ?? "This week"}</h2>
            <button type="button" className="week-arrow" onClick={() => data?.next && setWeek(data.next)} disabled={!data?.next} aria-label="Next week">
              ›
            </button>
          </div>
          {data?.this_week ? (
            <span className="this-week">This week</span>
          ) : (
            <button type="button" className="this-week button" onClick={() => setWeek(null)}>
              This week
            </button>
          )}
        </div>
        <div className="week-grid">
          {(data?.days ?? []).map((day) => (
            <div className="week-col" key={day.date}>
              <div className="week-col-head">
                {day.weekday}, {day.month_day}
              </div>
              {day.closed && <div className="week-closed">Market closed</div>}
              {!day.closed && day.rows.length === 0 && <div className="week-closed">—</div>}
              {orderedRows(day.rows, mode).map((row) => (
                <WeekRow key={row.symbol} row={row} mode={mode} />
              ))}
            </div>
          ))}
        </div>
      </section>

      <section className="card morning-compare" aria-label="Check-in comparison">
        <div className="compare-head">
          <h2>How each time has done</h2>
          <p className="muted small">1R is 1% of the entry. Average R gives each morning one vote. Expectancy is R per fill. The stop is 1% under the entry, and a gap through it still books −1R. MFE is the best R before the stop or day 5. QQQ is the same clock, without a stop.</p>
        </div>
        <div className="table-card">
          <table className="scan-table morning-table">
            <thead>
              <tr>
                <th>Time</th>
                <th className="num">Days</th>
                <th className="num">Fills</th>
                <th className="num">Qualified</th>
                {COMPARE.map((h) => (
                  <th key={h} className="num">{COMPARE_LABEL[h]}</th>
                ))}
                <th className="num">Win</th>
                <th className="num">Stop</th>
                <th className="num">Gaps</th>
                <th className="num">Total R</th>
                <th className="num">Expectancy</th>
                <th className="num">MFE</th>
              </tr>
            </thead>
            <tbody>
              {CHECK_INS.map((id) => (
                <tr key={id} className={best?.window === id ? "is-best" : undefined}>
                  <th scope="row">{displayTime(id)}</th>
                  <StatCells stat={stats?.windows[id]} stopped qualified={stats?.windows[id]?.avg_qualified ?? null} />
                </tr>
              ))}
              <tr>
                <th scope="row">QQQ 10:00</th>
                <StatCells stat={stats?.qqq["10:00"] as WindowStat | undefined} stopped={false} qualified={null} />
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <SingleEntryTable stats={stats?.single_entry} />
      <StratReversalTable stats={stats?.strat_reversal} />
      <CrossTriggerTable stats={stats?.cross_trigger} />
      <ReclaimTable stats={stats?.ema_reclaim} />
    </div>
  );
}

function ReclaimTable({ stats }: { stats: MorningWeek["stats"]["ema_reclaim"] }) {
  if (!stats?.panels?.length) return null;
  const sentence = reclaimSentence(stats);
  return (
    <section className="card single-entry reclaim-entry" aria-label="EMA pullback reclaim study">
      <div className="compare-head">
        <h2>EMA pullback reclaim</h2>
        <p className="muted small">{stats.definition}</p>
        {sentence && <p className="strat-best">{sentence}</p>}
      </div>
      <div className="reclaim-grid">
        {stats.panels.map((panel) => (
          <div className="single-rule" key={panel.title}>
            <h3>{panel.title}</h3>
            {panel.books.map((id) => (
              <p className="muted small" key={id}>{reclaimNote(stats.books[id])}</p>
            ))}
            <div className="table-card">
              <table className="scan-table morning-table single-table strat-table">
                <thead>
                  <tr>
                    <th> </th>
                    {panel.books.map((id) => (
                      <th className="num" key={id}>{stats.books[id]?.label ?? id}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {SINGLE_HORIZONS.map((horizon) => (
                    <Fragment key={horizon}>
                      <tr className="single-horizon">
                        <th colSpan={1 + panel.books.length}>{COMPARE_LABEL[horizon]}</th>
                      </tr>
                      {STRAT_METRICS.map((metric) => (
                        <tr key={`${horizon}-${metric.key}`}>
                          <th scope="row">{metric.label}</th>
                          {panel.books.map((id) => {
                            const block = stats.books[id]?.horizons[horizon];
                            const raw = block?.[metric.key];
                            const tone = metric.kind === "pct" || metric.kind === "r" || metric.kind === "r1" ? returnTone(typeof raw === "number" ? raw : null) : "";
                            return (
                              <td className={`num ${tone}`} key={id}>
                                {formatSingle(block, metric.key, metric.kind)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function CrossTriggerTable({ stats }: { stats: MorningWeek["stats"]["cross_trigger"] }) {
  if (!stats?.order?.length) return null;
  const sentence = crossSentence(stats);
  return (
    <section className="card single-entry cross-entry" aria-label="RMA cross trigger study">
      <div className="compare-head">
        <h2>RMA cross trigger</h2>
        <p className="muted small">{stats.definition}</p>
        {sentence && <p className="strat-best">{sentence}</p>}
      </div>
      <div className="single-rule">
        {stats.order.map((id) => (
          <p className="muted small" key={id}>{crossNote(stats.books[id])}</p>
        ))}
        <div className="table-card">
          <table className="scan-table morning-table single-table strat-table">
            <thead>
              <tr>
                <th> </th>
                {stats.order.map((id) => (
                  <th className="num" key={id}>{stats.books[id]?.label ?? id}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SINGLE_HORIZONS.map((horizon) => (
                <Fragment key={horizon}>
                  <tr className="single-horizon">
                    <th colSpan={1 + stats.order.length}>{COMPARE_LABEL[horizon]}</th>
                  </tr>
                  {STRAT_METRICS.map((metric) => (
                    <tr key={`${horizon}-${metric.key}`}>
                      <th scope="row">{metric.label}</th>
                      {stats.order.map((id) => {
                        const block = stats.books[id]?.horizons[horizon];
                        const raw = block?.[metric.key];
                        const tone = metric.kind === "pct" || metric.kind === "r" || metric.kind === "r1" ? returnTone(typeof raw === "number" ? raw : null) : "";
                        return (
                          <td className={`num ${tone}`} key={id}>
                            {formatSingle(block, metric.key, metric.kind)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function StratReversalTable({ stats }: { stats: MorningWeek["stats"]["strat_reversal"] }) {
  if (!stats?.panels?.length) return null;
  const sentence = stratSentence(stats);
  return (
    <section className="card single-entry strat-entry" aria-label="Strat reversal study">
      <div className="compare-head">
        <h2>Strat reversal, 15-minute and 30-minute</h2>
        <p className="muted small">{stats.definition}</p>
        {sentence && <p className="strat-best">{sentence}</p>}
      </div>
      <div className="single-grid">
        {stats.panels.map((panel) => (
          <div className="single-rule" key={panel.title}>
            <h3>{panel.title}</h3>
            {panel.books.map((id) => (
              <p className="muted small" key={id}>{stratNote(stats.books[id])}</p>
            ))}
            <div className="table-card">
              <table className="scan-table morning-table single-table strat-table">
                <thead>
                  <tr>
                    <th> </th>
                    {panel.books.map((id) => (
                      <th className="num" key={id}>{stats.books[id]?.label ?? id}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {SINGLE_HORIZONS.map((horizon) => (
                    <Fragment key={horizon}>
                      <tr className="single-horizon">
                        <th colSpan={1 + panel.books.length}>{COMPARE_LABEL[horizon]}</th>
                      </tr>
                      {STRAT_METRICS.map((metric) => (
                        <tr key={`${horizon}-${metric.key}`}>
                          <th scope="row">{metric.label}</th>
                          {panel.books.map((id) => {
                            const block = stats.books[id]?.horizons[horizon];
                            const raw = block?.[metric.key];
                            const tone = metric.kind === "pct" || metric.kind === "r" || metric.kind === "r1" ? returnTone(typeof raw === "number" ? raw : null) : "";
                            return (
                              <td className={`num ${tone}`} key={id}>
                                {formatSingle(block, metric.key, metric.kind)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
