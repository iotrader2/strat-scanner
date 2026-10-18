import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import {
  CHECK_INS,
  bestSentence,
  displayTime,
  orderedRows,
  outcomeLine,
  returnTone,
  shownRank,
  signedPct,
  type MorningMode,
  type MorningRow,
  type MorningWeek,
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
  const ret = outcome?.d3_ret;
  const rank = shownRank(row, mode);
  return (
    <div className="week-row">
      <span className="week-rank">{rank ?? "–"}</span>
      <TickerLogo symbol={row.symbol} />
      <Link className="week-sym" to={`/stock/${encodeURIComponent(row.symbol)}`}>
        {row.symbol}
      </Link>
      {mode !== "leaders" && (
        <span className={`week-ret ${returnTone(ret)}`} title={outcomeLine(outcome)}>
          {signedPct(ret)}
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

function StatCells({ stat, stopped }: { stat: WindowStat | undefined; stopped: boolean }) {
  if (!stat) {
    return (
      <>
        <td className="num">—</td>
        {COMPARE.map((h) => (
          <td key={h} className="num">—</td>
        ))}
        <td className="num">—</td>
        <td className="num">—</td>
        <td className="num">—</td>
      </>
    );
  }
  const primary = stat.horizons.d3;
  return (
    <>
      <td className="num">{primary?.n_days || stat.n_days || "—"}</td>
      {COMPARE.map((h) => {
        const value = stat.horizons[h]?.avg;
        return (
          <td key={h} className={`num ${returnTone(value)}`}>
            {signedPct(value)}
          </td>
        );
      })}
      <td className="num">{primary?.win_rate == null ? "—" : `${Math.round(primary.win_rate * 100)}%`}</td>
      <td className="num">{!stopped || primary?.stop_hit_rate == null ? "—" : `${Math.round(primary.stop_hit_rate * 100)}%`}</td>
      <td className={`num ${returnTone(stopped ? primary?.expectancy : primary?.avg)}`}>
        {signedPct(stopped ? primary?.expectancy : primary?.avg)}
      </td>
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
              {signedPct(best.vs_open)} versus buying the same names at the open
              {" · "}
              {signedPct(best.vs_qqq)} versus QQQ from the same minute
              {" · "}
              {best.n_days} mornings. Names in one morning move together, so this is not {best.n_trades} separate bets.
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
          : `Best at ${displayTime(mode)}, from the move since the open, versus QQQ, and the opening range. The number is the +3 day return.`}
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
          <p className="muted small">Equal-weight basket of that day's top 10. Expectancy uses the candle-low stop. QQQ is the same clock, without a stop.</p>
        </div>
        <div className="table-card">
          <table className="scan-table morning-table">
            <thead>
              <tr>
                <th>Time</th>
                <th className="num">Days</th>
                {COMPARE.map((h) => (
                  <th key={h} className="num">{COMPARE_LABEL[h]}</th>
                ))}
                <th className="num">Win +3d</th>
                <th className="num">Stop</th>
                <th className="num">Expectancy +3d</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Open</th>
                <StatCells stat={stats?.windows.open} stopped={false} />
              </tr>
              {CHECK_INS.map((id) => (
                <tr key={id} className={best?.window === id ? "is-best" : undefined}>
                  <th scope="row">{displayTime(id)}</th>
                  <StatCells stat={stats?.windows[id]} stopped />
                </tr>
              ))}
              <tr>
                <th scope="row">QQQ 10:00</th>
                <StatCells stat={stats?.qqq["10:00"] as WindowStat | undefined} stopped={false} />
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
