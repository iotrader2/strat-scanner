import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import {
  CHECK_INS,
  PULLBACK_COL,
  PULLBACK_REF,
  WINDOW_COL,
  RMA_CAP_LABEL,
  SINGLE_HORIZONS,
  SINGLE_METRICS,
  SINGLE_RULES,
  STRAT_METRICS,
  bestSentence,
  crossNote,
  crossSentence,
  displayTime,
  pullbackNote,
  pullbackSentence,
  sweepSentence,
  windowNote,
  windowSentence,
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
  type SweepBook,
  type SweepExample,
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
  const rmaBooks = (stats.caps?.length ? stats.caps : ["rma_all", "rma_first"]).filter((id) => stats.books[id]);
  const rules = [
    { title: "10:30 close, above the 20 RMA", books: rmaBooks, wide: rmaBooks.length > 2, caps: true },
    { title: SINGLE_RULES[1].title, books: [...SINGLE_RULES[1].books], wide: false, caps: false },
  ];
  return (
    <section className="card single-entry" aria-label="Single entry study">
      <div className="compare-head">
        <h2>Single entry, low of day</h2>
        <p className="muted small">{stats.definition}</p>
        {stats.caps_note && <p className="muted small">{stats.caps_note}</p>}
      </div>
      <div className="single-grid">
        {rules.map((rule) => (
          <div className={rule.wide ? "single-rule wide" : "single-rule"} key={rule.title}>
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
                      <th className="num" key={id}>{rule.caps ? (RMA_CAP_LABEL[id] ?? stats.books[id]?.label ?? id) : (stats.books[id]?.label ?? id)}</th>
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
      <StopSweepTable stats={stats?.stop_sweep} />
      <PullbackTable pullback={stats?.strat_pullback} single={stats?.single_entry} />
      <WindowPullbackTable pullback={stats?.strat_pullback} single={stats?.single_entry} />
      <StratReversalTable stats={stats?.strat_reversal} />
      <CrossTriggerTable stats={stats?.cross_trigger} />
      <ReclaimTable stats={stats?.ema_reclaim} />
    </div>
  );
}

function rate(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `$${Math.abs(value).toFixed(2)}`;
}

function StopSweepTable({ stats }: { stats: MorningWeek["stats"]["stop_sweep"] }) {
  const books = (stats?.book_order ?? []).map((id) => stats?.books[id]).filter((book): book is SweepBook => !!book?.order?.length);
  if (!books.length) return null;
  return (
    <section className="card single-entry sweep-entry" aria-label="10:30 stop sweep">
      <div className="compare-head">
        <h2>Stop sweep, 10:30 rank tie</h2>
        <p className="muted small">{stats?.definition}</p>
        <p className="muted small">{stats?.noise}</p>
        {books.map((book) => {
          const sentence = sweepSentence(book);
          return sentence ? <p className="strat-best" key={book.id}>{sentence}</p> : null;
        })}
      </div>
      <SweepExampleBlock example={stats?.example} />
      {books.map((book) => (
        <div className="single-rule wide" key={book.id}>
          <h3>{book.label}</h3>
          <div className="table-card">
            <table className="scan-table morning-table single-table strat-table">
              <thead>
                <tr>
                  <th>Stop</th>
                  <th className="num">Stop %</th>
                  <th className="num">Skip</th>
                  <th className="num">R/trade</th>
                  <th className="num">Total R</th>
                  <th className="num">Avg %</th>
                  <th className="num">Total %</th>
                  <th className="num">Win</th>
                  <th className="num">Stop</th>
                  <th className="num">Gaps</th>
                  <th className="num">MFE</th>
                  <th className="num">Median</th>
                  <th className="num">Best</th>
                  <th className="num">Worst</th>
                  <th className="num">30m</th>
                  <th className="num">Slip R</th>
                </tr>
              </thead>
              <tbody>
                {book.order.map((id) => {
                  const stop = book.stops[id];
                  const d3 = stop?.horizons.d3;
                  if (!stop || !d3) return null;
                  const klass = id === book.best_r ? "is-best" : id === book.tight ? "is-tight" : undefined;
                  return (
                    <tr key={id} className={klass}>
                      <th scope="row">{stop.label}</th>
                      <td className="num">{stop.avg_stop_pct == null ? "—" : `${Math.abs(stop.avg_stop_pct).toFixed(2)}%`}</td>
                      <td className="num">{stop.n_skipped}</td>
                      <td className={`num ${returnTone(d3.r_per_trade)}`}>{signedR(d3.r_per_trade, 2)}</td>
                      <td className={`num ${returnTone(d3.total_r)}`}>{signedR(d3.total_r, 1)}</td>
                      <td className={`num ${returnTone(d3.avg_pct)}`}>{signedPct(d3.avg_pct, 2)}</td>
                      <td className={`num ${returnTone(d3.total_pct)}`}>{signedPct(d3.total_pct, 1)}</td>
                      <td className="num">{rate(d3.win_rate)}</td>
                      <td className="num">{rate(d3.stop_hit_rate)}</td>
                      <td className="num">{d3.gap_count ?? "—"}</td>
                      <td className={`num ${returnTone(d3.avg_mfe)}`}>{signedR(d3.avg_mfe, 2)}</td>
                      <td className={`num ${returnTone(d3.median_r)}`}>{signedR(d3.median_r, 2)}</td>
                      <td className={`num ${returnTone(d3.best_r)}`}>{signedR(d3.best_r, 2)}</td>
                      <td className={`num ${returnTone(d3.worst_r)}`}>{signedR(d3.worst_r, 2)}</td>
                      <td className="num">{rate(stop.fast_stop_rate)}</td>
                      <td className={`num ${returnTone(d3.slip_r_per_trade)}`}>{signedR(d3.slip_r_per_trade, 2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="table-card">
            <table className="scan-table morning-table single-table strat-table">
              <thead>
                <tr>
                  <th>Stop</th>
                  {COMPARE.map((horizon) => <th className="num" key={horizon}>{COMPARE_LABEL[horizon]} R</th>)}
                  {COMPARE.map((horizon) => <th className="num" key={`${horizon}-pct`}>{COMPARE_LABEL[horizon]} %</th>)}
                </tr>
              </thead>
              <tbody>
                {book.order.map((id) => {
                  const stop = book.stops[id];
                  if (!stop) return null;
                  return (
                    <tr key={`${id}-path`} className={id === book.tight ? "is-tight" : undefined}>
                      <th scope="row">{stop.label}</th>
                      {COMPARE.map((horizon) => {
                        const value = stop.horizons[horizon]?.r_per_trade;
                        return <td className={`num ${returnTone(value)}`} key={horizon}>{signedR(value, 2)}</td>;
                      })}
                      {COMPARE.map((horizon) => {
                        const value = stop.horizons[horizon]?.avg_pct;
                        return <td className={`num ${returnTone(value)}`} key={`${horizon}-pct`}>{signedPct(value, 2)}</td>;
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </section>
  );
}

function SweepExampleBlock({ example }: { example?: SweepExample | null }) {
  if (!example) return null;
  const tight = example.tight;
  return (
    <div className="single-rule wide">
      <h3>One rank-tie morning</h3>
      <p className="muted small">
        {example.date} {example.symbol}{example.name ? ` (${example.name})` : ""}, leader rank {example.leader_rank ?? "—"}.
        Cross at {example.cross_time}
        {example.cross_close != null ? `, close ${money(example.cross_close)}` : ""}
        {example.cross_rma != null ? `, 20 RMA ${money(example.cross_rma)}` : ""}.
        {" "}{example.why}
      </p>
      <p className="muted small">
        10:30 entry {money(example.entry)}. Low of day {money(example.stop)}, {example.stop_pct == null ? "—" : `${Math.abs(example.stop_pct).toFixed(2)}%`} under the entry, 1R {money(example.risk)}.
        Day 3 books {signedR(example.day3_r, 2)} against the book average {signedR(example.book_avg_r, 2)}.
        {example.symbol_first && example.symbol_first !== example.symbol ? ` The symbol tie-break buys ${example.symbol_first} first.` : ""}
        {" "}{example.stopped ? `The low-of-day stop was hit.${hitDetail(example.hit)}` : "The low-of-day stop was not hit through the day-5 close."}
      </p>
      {tight && !tight.missing && (
        <p className="muted small">
          {intight(tight, example)}
        </p>
      )}
      {example.path?.length > 0 && (
        <div className="table-card">
          <table className="scan-table morning-table single-table strat-table">
            <thead>
              <tr>
                <th> </th>
                <th>Date</th>
                <th className="num">Close</th>
                <th className="num">Close %</th>
                <th className="num">Close R</th>
                <th className="num">Booked %</th>
                <th className="num">Booked R</th>
              </tr>
            </thead>
            <tbody>
              {example.path.map((item) => (
                <tr key={item.horizon}>
                  <th scope="row">{COMPARE_LABEL[item.horizon as keyof typeof COMPARE_LABEL] ?? item.horizon}</th>
                  <td>{item.date}</td>
                  <td className="num">{money(item.close)}</td>
                  <td className={`num ${returnTone(item.close_pct)}`}>{signedPct(item.close_pct, 2)}</td>
                  <td className={`num ${returnTone(item.close_r)}`}>{signedR(item.close_r, 2)}</td>
                  <td className={`num ${returnTone(item.booked_pct)}`}>{signedPct(item.booked_pct, 2)}</td>
                  <td className={`num ${returnTone(item.booked_r)}`}>{signedR(item.booked_r, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tight && !tight.missing && !tight.skipped && (tight.path?.length ?? 0) > 0 && (
        <div className="table-card">
          <table className="scan-table morning-table single-table strat-table">
            <caption className="muted small">{tight.label} on this fill. Close is the unstopped session close. Booked is what this stop keeps.</caption>
            <thead>
              <tr>
                <th> </th>
                <th>Date</th>
                <th className="num">Close</th>
                <th className="num">Close %</th>
                <th className="num">Close R</th>
                <th className="num">Booked %</th>
                <th className="num">Booked R</th>
              </tr>
            </thead>
            <tbody>
              {tight.path!.map((item) => (
                <tr key={`tight-${item.horizon}`}>
                  <th scope="row">{COMPARE_LABEL[item.horizon as keyof typeof COMPARE_LABEL] ?? item.horizon}</th>
                  <td>{item.date}</td>
                  <td className="num">{money(item.close)}</td>
                  <td className={`num ${returnTone(item.close_pct)}`}>{signedPct(item.close_pct, 2)}</td>
                  <td className={`num ${returnTone(item.close_r)}`}>{signedR(item.close_r, 2)}</td>
                  <td className={`num ${returnTone(item.booked_pct)}`}>{signedPct(item.booked_pct, 2)}</td>
                  <td className={`num ${returnTone(item.booked_r)}`}>{signedR(item.booked_r, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function hitDetail(hit?: SweepExample["hit"]): string {
  if (!hit?.clock) return "";
  const offset = hit.offset ?? 0;
  const session = hit.session ? ` (${hit.session})` : "";
  const label = offset === 0 ? "on the entry session" : `on the +${offset} session`;
  const how = hit.gapped ? "opened through the stop" : "traded down to the stop";
  return ` It was hit ${label}${session}, the 5-minute bar ending ${hit.clock}. The bar ${how} (open ${money(hit.open)}, low ${money(hit.low)}).`;
}

function intight(tight: NonNullable<SweepExample["tight"]>, example: SweepExample): string {
  if (tight.skipped) {
    return `The tightest stop near the top, ${tight.label}, is ${money(tight.stop)}, which is not under the ${money(example.entry)} entry, so this variant skips the trade.`;
  }
  const fast = tight.fast_stop ? " It was inside the first 30 minutes." : "";
  const booked = tight.day3_pct == null ? "" : ` and ${signedPct(tight.day3_pct, 2)}`;
  return `The tightest stop near the top is ${tight.label} at ${money(tight.stop)} (${tight.stop_pct == null ? "—" : `${Math.abs(tight.stop_pct).toFixed(2)}%`}, 1R ${money(tight.risk)}). Day 3 books ${signedR(tight.day3_r, 2)}${booked}.${fast}${hitDetail(tight.hit)}`;
}

function PullbackTable({
  pullback,
  single,
}: {
  pullback: MorningWeek["stats"]["strat_pullback"];
  single: MorningWeek["stats"]["single_entry"];
}) {
  if (!pullback?.panels?.length) return null;
  const sentence = pullbackSentence(pullback);
  return (
    <section className="card single-entry pullback-entry" aria-label="5-minute Strat pullback study">
      <div className="compare-head">
        <h2>5-minute Strat pullback</h2>
        <p className="muted small">{pullback.definition}</p>
        {sentence && <p className="strat-best">{sentence}</p>}
      </div>
      <div className="pullback-grid">
        {pullback.panels.map((panel) => {
          const columns = panel.books.flatMap((id, index) => {
            const ref = panel.refs[index];
            const pair: { id: string; source: "pullback" | "rma" }[] = [{ id, source: "pullback" }];
            if (ref && single?.books[ref]) pair.push({ id: ref, source: "rma" });
            return pair;
          });
          return (
            <div className="single-rule" key={panel.title}>
              <h3>{panel.title}</h3>
              {panel.books.map((id) => (
                <p className="muted small" key={id}>{pullbackNote(pullback.books[id])}</p>
              ))}
              <div className="table-card">
                <table className="scan-table morning-table single-table strat-table">
                  <thead>
                    <tr>
                      <th> </th>
                      {columns.map((col) => (
                        <th className="num" key={`${col.source}-${col.id}`}>
                          {col.source === "rma" ? (PULLBACK_REF[col.id] ?? col.id) : (PULLBACK_COL[col.id] ?? pullback.books[col.id]?.label ?? col.id)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {SINGLE_HORIZONS.map((horizon) => (
                      <Fragment key={horizon}>
                        <tr className="single-horizon">
                          <th colSpan={1 + columns.length}>{COMPARE_LABEL[horizon]}</th>
                        </tr>
                        {SINGLE_METRICS.map((metric) => (
                          <tr key={`${horizon}-${metric.key}`}>
                            <th scope="row">{metric.label}</th>
                            {columns.map((col) => {
                              const block = col.source === "rma"
                                ? single?.books[col.id]?.horizons[horizon]
                                : pullback.books[col.id]?.horizons[horizon];
                              const raw = block?.[metric.key];
                              const tone = metric.kind === "pct" || metric.kind === "r" || metric.kind === "r1" ? returnTone(typeof raw === "number" ? raw : null) : "";
                              return (
                                <td className={`num ${tone}`} key={`${col.source}-${col.id}`}>
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
          );
        })}
      </div>
    </section>
  );
}

function WindowPullbackTable({
  pullback,
  single,
}: {
  pullback: MorningWeek["stats"]["strat_pullback"];
  single: MorningWeek["stats"]["single_entry"];
}) {
  const window = pullback?.window;
  if (!window?.order?.length) return null;
  const sentence = windowSentence(window, pullback?.benchmark);
  const triggers = window.triggers;
  const columns: { id: string; source: "pullback" | "rma" }[] = [
    ...window.order.map((id) => ({ id, source: "pullback" as const })),
    ...window.refs.filter((id) => single?.books[id]).map((id) => ({ id, source: "rma" as const })),
  ];
  return (
    <section className="card single-entry pullback-entry" aria-label="10:00 to 10:30 Strat pullback">
      <div className="compare-head">
        <h2>Pullback, 10:00 to 10:30</h2>
        <p className="muted small">{window.definition}</p>
        {sentence && <p className="strat-best">{sentence}</p>}
        {triggers && (
          <p className="muted small">
            Before the cap, {triggers["0"]} {triggers["0"] === 1 ? "morning" : "mornings"} had no trigger in the window, {triggers["1"]} had one, {triggers["2"]} had two, and {triggers.more} had three or more.
          </p>
        )}
      </div>
      <div className="pullback-grid">
        <div className="single-rule">
          {window.order.map((id) => (
            <p className="muted small" key={id}>{windowNote(window.books[id])}</p>
          ))}
          <div className="table-card">
            <table className="scan-table morning-table single-table strat-table">
              <thead>
                <tr>
                  <th> </th>
                  {columns.map((col) => (
                    <th className="num" key={`${col.source}-${col.id}`}>
                      {col.source === "rma" ? (PULLBACK_REF[col.id] ?? col.id) : (WINDOW_COL[col.id] ?? window.books[col.id]?.label ?? col.id)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {SINGLE_HORIZONS.map((horizon) => (
                  <Fragment key={horizon}>
                    <tr className="single-horizon">
                      <th colSpan={1 + columns.length}>{COMPARE_LABEL[horizon]}</th>
                    </tr>
                    {SINGLE_METRICS.map((metric) => (
                      <tr key={`${horizon}-${metric.key}`}>
                        <th scope="row">{metric.label}</th>
                        {columns.map((col) => {
                          const block = col.source === "rma"
                            ? single?.books[col.id]?.horizons[horizon]
                            : window.books[col.id]?.horizons[horizon];
                          const raw = block?.[metric.key];
                          const tone = metric.kind === "pct" || metric.kind === "r" || metric.kind === "r1" ? returnTone(typeof raw === "number" ? raw : null) : "";
                          return (
                            <td className={`num ${tone}`} key={`${col.source}-${col.id}`}>
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
      </div>
    </section>
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
