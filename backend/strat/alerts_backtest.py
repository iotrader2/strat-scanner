"""Backtest of the 15-minute alert rules over past sessions, with the names the scanner would have picked each day.

    cd backend && .venv/bin/python -m strat.alerts_backtest --months 3 --out ../backtest

For every session in the window:

1. The market is scanned as of the **previous** close (prices, relative strength, themes and daily setups are all
   recomputed from history up to that date, splits applied point-in-time), and the alert names are picked with the
   same functions the live poll uses (``api.alert_symbols`` / ``alert_short_symbols``: daily setup, theme gate,
   dollar volume, ATR floor, caps). Shorts go through the mapped inverse ETFs.
2. Each name's 15-minute SIP bars for that session run through :func:`strat.alerts.simulate` with the EMAs carried
   over from the sessions before, exactly as the live poll and the replay do.
3. Open positions are held overnight and walked through later sessions with ``carry_alert`` / ``advance_carried``
   (stop on the day's bars, daily trim ladder on the last bar's close as the 15:59 price). A held name cannot start
   a new trade. Positions still open at the end are marked at the last close.
4. Each trade gets the frozen setup score (``details["score"]``), so the score can be checked against R.

``--variants`` reruns the same days with one rule changed at a time (the bars and scans are cached, so this is cheap).

What this does not reproduce: names you added to the watchlist by hand, names the live scan adds during the session
(the list here is fixed at the previous close), slippage (fills are at the trigger, stops at the stop or the open on
a gap), and delisted or removed index members (today's universe). Alpaca drops 15-minute bars with no trades.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from . import alerts as rules
from . import alerts_live
from .alerts import Alert, Context, Settings, advance_carried, carry_alert, context_from_closes, ema_periods_for, simulate
from .inverse_etfs import INVERSE_ETF_MAP, map_underlyings_to_etfs
from .leadership import BENCHMARK
from .scheduler import CLOSE, ET, OPEN

SEED_CALENDAR_DAYS = 45  # 15-minute history before the window, to seed the 6 / 20 / 120 EMAs
FETCH_BATCH = 40  # symbols per 15-minute history request group (keeps a batch's raw bars small in memory)
DAILY_KEEP = 200  # finished daily closes handed to the trim EMAs

# name -> setting overrides, each relative to the current defaults.
VARIANTS: dict[str, dict[str, float]] = {
    "current rules": {},
    "cutoff back to 12:00 ET": {"trade_window_minutes": 150},
    "no 20 EMA filter": {"cross_above_ema": 0},
    "no minimum stop": {"min_stop_pct": 0},
    "all three off (rules before)": {"trade_window_minutes": 150, "cross_above_ema": 0, "min_stop_pct": 0},
}


def _log(msg: str) -> None:
    print(f"[alerts-backtest] {msg}", file=sys.stderr, flush=True)


def _ts(raw) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(timezone.utc)


# ------------------------------------------------------------------------------------------------------ daily scans


def scan_days(sessions: Sequence[date], daily: Mapping[str, pd.DataFrame], splits: Mapping, settings: Settings) -> dict:
    """session -> {"longs", "shorts", "labels", "rows" (picked names' scan rows), "daily" (their closes)}.

    The scan for a session uses bars up to the session before it.
    """
    from . import api
    from .backtest import _as_of_frames
    from .members import effective_universe
    from .scanner import LEADERS, scan_all
    from .themes import load_themes
    from .universe import load_universe

    members = effective_universe(load_universe())
    try:
        themes = load_themes()
    except Exception:  # noqa: BLE001 — without themes the theme gate lets nothing through; say so
        _log("themes could not be loaded: with the theme gate on no name will qualify")
        themes = None
    calendar = sorted(daily[BENCHMARK].index)
    out: dict[str, dict] = {}
    for n, day in enumerate(sessions):
        before = [t for t in calendar if t.date() < day]
        if not before:
            continue
        as_of = before[-1]
        frames = _as_of_frames(daily, as_of, splits)
        rows = scan_all(members, frames, themes, method=LEADERS, changes=False).rows
        longs = api.alert_symbols(rows, settings)
        shorts = api.alert_short_symbols(rows, settings)
        labels = api.alert_daily_labels(rows, settings)
        etfs = [etf for etf, _ in map_underlyings_to_etfs(shorts)] if settings.inverse_etf_shorts and settings.shorts else []
        need = set(longs) | set(shorts) | set(etfs)
        by_sym = {r["symbol"]: r for r in rows if r.get("symbol") in need}
        closes = {
            s: [float(c) for c in frames[s]["close"].tolist()[-DAILY_KEEP:]]
            for s in need if frames.get(s) is not None and len(frames[s])
        }
        out[day.isoformat()] = {
            "as_of": as_of.date().isoformat(), "longs": longs, "shorts": shorts,
            "labels": {s: labels[s] for s in labels if s in need}, "rows": by_sym, "daily": closes,
        }
        _log(f"scan {n + 1}/{len(sessions)} {day} (as of {as_of.date()}): {len(longs)} longs, {len(shorts)} shorts")
    return out


# --------------------------------------------------------------------------------------------------- 15-minute bars


def fetch_15m(client, symbols: Sequence[str], start: date, end: date) -> dict[str, dict[str, list[dict]]]:
    """symbol -> session (ISO) -> regular-session 15-minute SIP bars (raw), oldest first."""
    out: dict[str, dict[str, list[dict]]] = {}
    lo = datetime.combine(start, time(0, 0), tzinfo=ET)
    hi = datetime.combine(end, CLOSE, tzinfo=ET) - timedelta(seconds=1)
    syms = list(dict.fromkeys(symbols))
    for i in range(0, len(syms), FETCH_BATCH):
        batch = syms[i : i + FETCH_BATCH]
        raw, invalid = client.bars(batch, alerts_live.BARS, lo, end=hi, feed="sip", adjustment="raw")
        for sym in batch:
            days: dict[str, list[dict]] = defaultdict(list)
            for b in raw.get(sym, []):
                t = _ts(b["t"])
                if alerts_live.slot(t) is None:
                    continue
                days[t.astimezone(ET).date().isoformat()].append(alerts_live._bar(b))
            out[sym] = {d: sorted(v, key=lambda x: x["t"]) for d, v in days.items()}
        del raw
        _log(f"15m bars {min(i + FETCH_BATCH, len(syms))}/{len(syms)} symbols (requests so far: {client.requests})")
    return out


# ------------------------------------------------------------------------------------------------------- simulation


def _context(sym: str, day: str, bars15: Mapping[str, Mapping[str, list]], scan: Mapping, settings: Settings,
             inverse: bool, n_bars: int) -> Context:
    days = bars15.get(sym) or {}
    closes = [float(b["c"]) for d in sorted(days) if d < day for b in days[d]]
    base = context_from_closes(closes, periods=ema_periods_for(settings))
    daily = (scan.get("daily") or {}).get(sym) or []
    last = (days.get(day) or [None])[-1]
    session_close = datetime.combine(date.fromisoformat(day), CLOSE, tzinfo=ET)
    mark = None
    if last is not None:
        at = (session_close - timedelta(minutes=1)).astimezone(timezone.utc)
        # On a half day the last bar ends before 15:59 ET: put the check at that bar's end.
        at = min(at, last["t"] + rules.BAR - timedelta(minutes=1))
        mark = {"price": float(last["c"]), "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "late": False}
    return Context(
        ma_tail=base.ma_tail, prev_close=base.prev_close, session_bars=n_bars,
        prior_daily_bars=() if inverse else tuple(daily), daily_closes=tuple(daily), close_mark=mark,
    )


def run(sessions: Sequence[date], scans: Mapping[str, Mapping], bars15: Mapping[str, Mapping[str, list]],
        settings: Settings) -> list[dict]:
    """Every alert over ``sessions`` as a record row, with carried positions walked to their exit."""
    done: list[dict] = []
    open_rows: dict[str, dict] = {}  # symbol -> stored row of the open position
    last_price: dict[str, float] = {}
    for day_d in sessions:
        day = day_d.isoformat()
        scan = scans.get(day)
        if scan is None:
            continue
        full = len((bars15.get(BENCHMARK) or {}).get(day) or []) or rules.SESSION_BARS
        qqq = (bars15.get(BENCHMARK) or {}).get(day)
        # Carried positions first: a name that is still held cannot start a new trade today.
        for sym in sorted(open_rows):
            bars = (bars15.get(sym) or {}).get(day)
            if not bars:
                continue
            last_price[sym] = float(bars[-1]["c"])
            row = open_rows[sym]
            ctx = _context(sym, day, bars15, _carry_scan(scans, day, sym, bars15), settings, True, len(bars))
            a = advance_carried(carry_alert(row, day), bars, ctx, settings)
            rec = _row(a)
            if a.status == "triggered":
                open_rows[sym] = rec
            else:
                del open_rows[sym]
                done.append(rec)
        short_pairs = map_underlyings_to_etfs(scan["shorts"]) if settings.inverse_etf_shorts and settings.shorts else []
        underlying = {etf: und for etf, und in short_pairs}
        picked = [s for s in scan["longs"] if s not in set(scan["shorts"])]
        for sym in list(dict.fromkeys(picked + sorted(underlying))):
            if sym in open_rows:
                continue
            bars = (bars15.get(sym) or {}).get(day)
            if not bars:
                continue
            inverse = sym in underlying and sym not in picked
            ctx = _context(sym, day, bars15, scan, settings, inverse, full)
            found = simulate(sym, day, bars, ctx, settings, side="long", skip_extension_cap=inverse)
            refs = (scan["labels"].get(underlying[sym] if inverse else sym) or {}).get("short" if inverse else "long") or []
            for a in found:
                if refs:
                    a.details["daily_setups"] = list(refs)
                if inverse:
                    a.details.update({"underlying": underlying[sym], "inverse_etf": True, "side_role": "short"})
                alerts_live.attach_entry_score(a, bars, qqq, scan["rows"].get(sym))
                rec = _row(a)
                rec["scan_score"] = (scan["rows"].get(sym) or {}).get("score")
                if a.status == "triggered":
                    open_rows[sym] = rec
                    last_price[sym] = float(bars[-1]["c"])
                else:
                    done.append(rec)
    for sym, row in open_rows.items():
        row["open_at_end"] = True
        row["r_multiple"] = rules.open_r(row, last_price.get(sym))
        done.append(row)
    done.sort(key=lambda r: (r["fired_at"], r["symbol"]))
    return done


def _carry_scan(scans: Mapping[str, Mapping], day: str, sym: str, bars15: Mapping) -> dict:
    """Daily closes for a carried name on ``day``: the day's scan when it still lists the name, else rebuilt from
    the last scan that had it plus the 15-minute closes of the sessions since."""
    scan = scans.get(day) or {}
    if sym in (scan.get("daily") or {}):
        return scan  # type: ignore[return-value]
    for d in sorted((k for k in scans if k < day), reverse=True):
        closes = (scans[d].get("daily") or {}).get(sym)
        if closes:
            later = [
                float(v[-1]["c"]) for k, v in sorted((bars15.get(sym) or {}).items())
                if scans[d]["as_of"] < k < day and v
            ]
            return {"daily": {sym: list(closes) + later}}
    return {"daily": {}}


def _row(a: Alert) -> dict:
    rec = a.record()
    rec["details"] = json.loads(rec["details"])
    return rec


# ----------------------------------------------------------------------------------------------------------- report


def _filled(rows: Sequence[Mapping]) -> list[Mapping]:
    return [r for r in rows if r.get("filled") and isinstance(r.get("r_multiple"), (int, float))]


def stats(rows: Sequence[Mapping]) -> dict:
    trades = _filled(rows)
    rs = [float(r["r_multiple"]) for r in trades]
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    equity = peak = dd = 0.0
    for x in rs:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return {
        "alerts": len(rows), "trades": len(trades),
        "fill_rate": round(100 * len(trades) / len(rows), 1) if rows else None,
        "win_rate": round(100 * len(wins) / len(rs), 1) if rs else None,
        "avg_r": round(statistics.fmean(rs), 3) if rs else None,
        "median_r": round(statistics.median(rs), 3) if rs else None,
        "total_r": round(sum(rs), 2),
        "avg_win": round(statistics.fmean(wins), 2) if wins else None,
        "avg_loss": round(statistics.fmean(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
        "hit_1_5r": round(100 * sum(1 for x in rs if x >= 1.5) / len(rs), 1) if rs else None,
        "big_3r": sum(1 for x in rs if x >= 3),
        "max_drawdown_r": round(dd, 2),
    }


def _fmt(v: Any, plus: bool = False) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:+.2f}" if plus else f"{v:g}"
    return str(v)


def _table(headers: Sequence[str], body: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


STAT_COLS = (
    ("Trades", "trades", False), ("Win %", "win_rate", False), ("Avg R", "avg_r", True), ("Median R", "median_r", True),
    ("Total R", "total_r", True), ("Profit factor", "profit_factor", False), ("R ≥ 1.5 %", "hit_1_5r", False),
    ("R ≥ 3", "big_3r", False), ("Max drawdown R", "max_drawdown_r", False),
)


def _stat_row(label: str, s: Mapping) -> list[str]:
    return [label] + [_fmt(s[k], plus) for _, k, plus in STAT_COLS]


def _group(rows: Sequence[Mapping], key) -> list[tuple[str, dict]]:
    buckets: dict[str, list] = defaultdict(list)
    for r in _filled(rows):
        k = key(r)
        if k is not None:
            buckets[k].append(r)
    return [(k, stats(v)) for k, v in sorted(buckets.items())]


def _fill_et(r: Mapping) -> Optional[datetime]:
    return _ts(r["fill_at"]).astimezone(ET) if r.get("fill_at") else None


def _stop_pct(r: Mapping) -> float:
    return abs(r["trigger_price"] - r["stop_price"]) / r["trigger_price"] * 100


def _bucket(value: float, edges: Sequence[float], unit: str = "") -> str:
    lo = None
    for i, e in enumerate(edges):
        if value < e:
            return f"{i}: {'under ' + format(e, 'g') if lo is None else format(lo, 'g') + ' to ' + format(e, 'g')}{unit}"
        lo = e
    return f"{len(edges)}: {lo:g}{unit} and over"


def _score(r: Mapping) -> Optional[float]:
    s = (r.get("details") or {}).get("score")
    v = s.get("score") if isinstance(s, Mapping) else None
    if v is None and isinstance(s, Mapping):
        v = s.get("total")
    return float(v) if isinstance(v, (int, float)) else None


def _hold_days(r: Mapping) -> Optional[int]:
    if not r.get("fill_at") or not r.get("exit_at"):
        return None
    return (_ts(r["exit_at"]).astimezone(ET).date() - _ts(r["fill_at"]).astimezone(ET).date()).days


def render(results: Mapping[str, Sequence[Mapping]], sessions: Sequence[date], scans: Mapping) -> str:
    base_name = next(iter(results))
    base = results[base_name]
    trades = _filled(base)
    names = [len(s["longs"]) + len(s["shorts"]) for s in scans.values()]
    out = [
        f"# Alert backtest {sessions[0]} to {sessions[-1]} ({len(sessions)} sessions)",
        "",
        f"Names checked per day: median {statistics.median(names) if names else 0:g}, "
        f"range {min(names) if names else 0} to {max(names) if names else 0}. "
        f"Alerts: {len(base)}; filled: {len(trades)}; still open at the end (marked at the last close): "
        f"{sum(1 for r in base if r.get('open_at_end'))}.",
        "",
        "## Rule variants",
        "",
        _table(["Variant"] + [h for h, _, _ in STAT_COLS], [_stat_row(n, stats(rows)) for n, rows in results.items()]),
        "",
        f"## Current rules by month",
        "",
        _table(["Month"] + [h for h, _, _ in STAT_COLS], [_stat_row(k, s) for k, s in _group(base, lambda r: r["session"][:7])]),
        "",
        "## By fill time (ET, start of the 15-minute bar)",
        "",
        _table(["Fill bar"] + [h for h, _, _ in STAT_COLS],
               [_stat_row(k, s) for k, s in _group(base, lambda r: _fill_et(r).strftime("%H:%M") if _fill_et(r) else None)]),
        "",
        "## By stop size (% of the buy)",
        "",
        _table(["Stop"] + [h for h, _, _ in STAT_COLS],
               [_stat_row(k[3:], s) for k, s in _group(base, lambda r: _bucket(_stop_pct(r), (0.5, 0.6, 0.7, 0.8, 0.9), "%"))]),
        "",
        "## By exit",
        "",
        _table(["Exit"] + [h for h, _, _ in STAT_COLS],
               [_stat_row(k, s) for k, s in _group(base, lambda r: "open at the end" if r.get("open_at_end") else r.get("exit_reason") or "?")]),
        "",
        "## By days held",
        "",
        _table(["Days"] + [h for h, _, _ in STAT_COLS],
               [_stat_row(k[3:], s) for k, s in _group(
                   base, lambda r: None if _hold_days(r) is None else _bucket(_hold_days(r), (1, 2, 4, 8), " days"))]),
        "",
        "## By side",
        "",
        _table(["Side"] + [h for h, _, _ in STAT_COLS],
               [_stat_row(k, s) for k, s in _group(base, lambda r: "short (inverse ETF)" if r["details"].get("inverse_etf") else "long")]),
        "",
        "## By daily setup (a trade counts under each of its setups)",
        "",
    ]
    by_setup: dict[str, list] = defaultdict(list)
    for r in trades:
        for ref in r["details"].get("daily_setups") or [{"label": "none"}]:
            by_setup[str(ref.get("label") or ref.get("kind"))].append(r)
    out += [
        _table(["Daily setup"] + [h for h, _, _ in STAT_COLS],
               [_stat_row(k, stats(v)) for k, v in sorted(by_setup.items(), key=lambda kv: -len(kv[1]))]),
        "",
        "## By setup score (quintiles of the frozen entry score)",
        "",
    ]
    scored = sorted((r for r in trades if _score(r) is not None), key=_score)
    if len(scored) >= 10:
        q = [scored[len(scored) * i // 5 : len(scored) * (i + 1) // 5] for i in range(5)]
        out.append(_table(
            ["Quintile", "Score range"] + [h for h, _, _ in STAT_COLS],
            [[f"{i + 1}{' (lowest)' if i == 0 else ' (highest)' if i == 4 else ''}",
              f"{_score(g[0]):.0f} to {_score(g[-1]):.0f}"] + _stat_row("", stats(g))[1:] for i, g in enumerate(q) if g],
        ))
        rho = pd.Series([_score(r) for r in scored]).corr(pd.Series([float(r["r_multiple"]) for r in scored]), method="spearman")
        out += ["", f"Spearman rank correlation of score with R: {rho:+.3f} over {len(scored)} trades."]
    else:
        out.append("Too few scored trades.")
    ranked = sorted(trades, key=lambda r: float(r["r_multiple"]))
    def line(r):
        return [r["session"], r["symbol"], _fill_et(r).strftime("%H:%M") if _fill_et(r) else "–",
                f"{_stop_pct(r):.2f}%", f"{float(r['r_multiple']):+.2f}",
                "open at the end" if r.get("open_at_end") else r.get("exit_reason") or "", _hold_days(r) if _hold_days(r) is not None else "–"]
    cols = ["Session", "Symbol", "Fill ET", "Stop", "R", "Exit", "Days held"]
    out += ["", "## Best 15 trades", "", _table(cols, [line(r) for r in reversed(ranked[-15:])]),
            "", "## Worst 15 trades", "", _table(cols, [line(r) for r in ranked[:15]])]
    return "\n".join(out) + "\n"


# -------------------------------------------------------------------------------------------------------------- main


def _load_or(path: Path, build, refresh: bool):
    if path.exists() and not refresh:
        with open(path, "rb") as fh:
            return pickle.load(fh)
    value = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest the 15-minute alert rules with the scanner's daily picks")
    ap.add_argument("--months", type=float, default=3.0, help="window length ending at --end")
    ap.add_argument("--end", default=None, help="last session (YYYY-MM-DD); default: the last finished session in the cache")
    ap.add_argument("--out", default="backtest", help="directory for the report, the trades and the data cache")
    ap.add_argument("--no-variants", action="store_true", help="only the current rules")
    ap.add_argument("--refresh", action="store_true", help="ignore the cached scans and 15-minute bars")
    ap.add_argument("--no-daily-refresh", action="store_true", help="use the daily price cache as it is")
    args = ap.parse_args(argv)

    from . import data
    from .alpaca import AlpacaClient
    from .members import effective_universe
    from .universe import load_universe

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    if not args.no_daily_refresh:
        symbols = [m.symbol for m in effective_universe(load_universe())]
        _log(f"refreshing the daily cache for {len(symbols)} symbols")
        data.refresh(symbols)
    daily = data.load_all_daily(adjust=False)
    splits = data.load_splits()
    if BENCHMARK not in daily:
        print("The price cache is empty. Run `npm run refresh` first.", file=sys.stderr)
        return 1
    calendar = [t.date() for t in sorted(daily[BENCHMARK].index)]
    end = date.fromisoformat(args.end) if args.end else calendar[-1]
    start = end - timedelta(days=round(args.months * 30.44))
    sessions = [d for d in calendar if start <= d <= end]
    if not sessions:
        print("No sessions in the window.", file=sys.stderr)
        return 1
    tag = f"{sessions[0]}_{sessions[-1]}"
    scans = _load_or(out / f"scans_{tag}.pkl", lambda: scan_days(sessions, daily, splits, settings), args.refresh)

    names = {BENCHMARK}
    for s in scans.values():
        names.update(s["longs"])
        names.update(etf for etf, _ in map_underlyings_to_etfs(s["shorts"]))
    client = AlpacaClient()
    bars15 = _load_or(
        out / f"bars15_{tag}.pkl",
        lambda: fetch_15m(client, sorted(names), sessions[0] - timedelta(days=SEED_CALENDAR_DAYS), sessions[-1]),
        args.refresh,
    )

    variants = {"current rules": {}} if args.no_variants else VARIANTS
    results: dict[str, list[dict]] = {}
    for name, overrides in variants.items():
        s = Settings.from_mapping({**settings.to_dict(), **overrides})
        results[name] = run(sessions, scans, bars15, s)
        st = stats(results[name])
        _log(f"{name}: {st['trades']} trades, total {st['total_r']}R, avg {st['avg_r']}R")
    report = render(results, sessions, scans)
    (out / f"report_{tag}.md").write_text(report)
    with open(out / f"trades_{tag}.json", "w") as fh:
        json.dump({"settings": settings.to_dict(), "sessions": [d.isoformat() for d in sessions], "results": results}, fh, default=str)
    flat = []
    for r in results["current rules"]:
        flat.append({
            "session": r["session"], "symbol": r["symbol"], "fired_at": r["fired_at"], "status": r["status"],
            "filled": r["filled"], "trigger": r["trigger_price"], "stop": r["stop_price"], "stop_pct": round(_stop_pct(r), 3),
            "fill_at": r.get("fill_at"), "exit_at": r.get("exit_at"), "exit_price": r.get("exit_price"),
            "exit_reason": r.get("exit_reason"), "r": r.get("r_multiple"), "score": _score(r),
            "open_at_end": bool(r.get("open_at_end")), "inverse_etf": bool(r["details"].get("inverse_etf")),
            "daily_setups": "; ".join(str(x.get("label")) for x in r["details"].get("daily_setups") or []),
        })
    pd.DataFrame(flat).to_csv(out / f"trades_{tag}.csv", index=False)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
