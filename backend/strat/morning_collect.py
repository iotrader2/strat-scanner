"""Build morning-leader history: point-in-time top 10, 15-minute bars, check-in ranks, outcomes.

Idempotent. A date that already has its snapshot, its bars and a finished +5 day result is left
alone. ``--recompute`` rebuilds ranks and outcomes from the bars on disk without downloading
again, which is how a weight change is applied.

Leaders for session D are the scanner's top 10 stocks as of the previous session's close
(the same cut-off as ``STRAT_AS_OF`` / the backtest). The session D bar is not an input.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import config, data
from .adjust import apply_splits
from .backtest import _as_of_frames
from .intraday import get_intraday_provider, today_et
from .leadership import BENCHMARK, is_leader
from .morning import (
    BENCHMARK as QQQ,
    OPEN_WINDOW,
    TOP_N,
    WINDOW_IDS,
    IntervalWeights,
    interval_features,
    open_entry,
    outcome_for_entry,
    rank_at_window,
    weights_from_env,
    window_end,
)
from .morning_store import (
    all_leaders,
    bar_coverage,
    delete_day,
    gap_dates,
    incomplete_result_dates,
    leader_dates,
    load_bars,
    mark_gap,
    replace_leaders,
    replace_ranks,
    replace_results,
    save_bars,
)
from .scanner import scan_all

ET = ZoneInfo("America/New_York")
CLOSE_DONE = time(16, 20)


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def next_weekday(day: date) -> date:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def trading_calendar(frames: dict[str, pd.DataFrame]) -> list[str]:
    qqq = frames.get(QQQ)
    if qqq is None or qqq.empty:
        return []
    return list(dict.fromkeys(ts.strftime("%Y-%m-%d") for ts in pd.DatetimeIndex(qqq.index).sort_values()))


def dates_in_window(calendar: list[str], months: int, today: date) -> list[str]:
    """Completed sessions in the window that have a prior close to score from."""
    start = (pd.Timestamp(today) - pd.DateOffset(months=months)).strftime("%Y-%m-%d")
    return [day for day in calendar if day >= start and any(prev < day for prev in calendar)]


def upcoming_session(calendar: list[str], today: date) -> str | None:
    """The next weekday after the last bar, when it is still in the future (Monday's list on Sunday)."""
    if not calendar:
        return None
    last = date.fromisoformat(calendar[-1])
    if last >= today:
        return None
    nxt = next_weekday(last)
    if nxt <= today:
        return None
    return nxt.isoformat()


def session_is_complete(day: str, today: date, clock: datetime | None = None) -> bool:
    if day < today.isoformat():
        return True
    if day > today.isoformat():
        return False
    now = clock or datetime.now(ET)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    return now.astimezone(ET).time() >= CLOSE_DONE


def top_leaders(rows: list[dict], n: int = TOP_N) -> list[dict]:
    """Highest leadership scores among stocks that pass the live scanner's leader gate."""
    picked = []
    for row in rows:
        if row.get("kind") != "stock":
            continue
        if row["price"] < config.MIN_PRICE or row["avg_dollar_volume"] < config.MIN_DOLLAR_VOLUME:
            continue
        breakdown = (row.get("leadership") or {}).get("breakdown")
        if not is_leader(row.get("rs"), breakdown):
            continue
        picked.append(row)
        if len(picked) >= n:
            break
    return picked


def leaders_on(
    buy_date: str,
    members,
    raw_by_symbol: dict[str, pd.DataFrame],
    splits: dict,
    themes,
    calendar: list[str],
    n: int = TOP_N,
) -> list[dict]:
    """Top ``n`` leaders for ``buy_date``, scored only on bars through the prior session."""
    priors = [day for day in calendar if day < buy_date]
    if not priors:
        return []
    as_of = priors[-1]
    frames = _as_of_frames(raw_by_symbol, pd.Timestamp(as_of), splits)
    result = scan_all(members, frames, themes, changes=False)
    out = []
    for rank, row in enumerate(top_leaders(result.rows, n), start=1):
        out.append(
            {
                "rank": rank,
                "symbol": row["symbol"],
                "score": round(float(row["score"]), 4),
                "rs": row.get("rs"),
                "name": row.get("name") or "",
                "as_of": as_of,
            }
        )
    return out


def _day_bars(frame: pd.DataFrame | None, day: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    start = pd.Timestamp(f"{day} 00:00:00")
    end = start + pd.Timedelta(days=1)
    return frame.loc[(frame.index >= start) & (frame.index < end)]


def _adjust_frames(frames: dict[str, pd.DataFrame], splits: dict, as_of: str) -> dict[str, pd.DataFrame]:
    return {sym: apply_splits(df, splits.get(sym, ()), as_of) for sym, df in frames.items()}


def compute_day(
    day: str,
    symbols: list[str],
    intraday: dict[str, pd.DataFrame],
    daily: dict[str, pd.DataFrame],
    calendar: list[str],
    weights: IntervalWeights,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Interval ranks, leader outcomes (including the open buy) and QQQ holds for one session."""
    forward = [pd.Timestamp(d) for d in calendar if d > day][:5]
    entry_day = pd.Timestamp(day)
    bars = {sym: _day_bars(intraday.get(sym), day) for sym in (*symbols, QQQ)}
    rank_rows: list[dict] = []
    leader_rows: list[dict] = []
    qqq_rows: list[dict] = []
    qqq_bars = bars.get(QQQ)

    for label in WINDOW_IDS:
        end = window_end(day, label)
        features = {sym: interval_features(bars.get(sym), qqq_bars, end) for sym in symbols}
        for row in rank_at_window(features, weights):
            rank_rows.append(
                {
                    "window": label,
                    "rank": row["rank"],
                    "symbol": row["symbol"],
                    "score": row["score"],
                    "day_move": row["day_move"],
                    "vs_qqq": row["vs_qqq"],
                    "or_position": row["or_position"],
                }
            )
        for sym, feat in features.items():
            if not feat:
                continue
            outcome = outcome_for_entry(
                entry=feat["entry_price"],
                stop=feat["candle_low"],
                day_bars=bars.get(sym),
                entry_end=end,
                daily=daily.get(sym),
                entry_day=entry_day,
                forward_days=forward,
            )
            leader_rows.append({"symbol": sym, "window": label, **outcome})
        q_feat = interval_features(qqq_bars, qqq_bars, end)
        if q_feat:
            qqq_rows.append(
                {
                    "symbol": QQQ,
                    "window": label,
                    **outcome_for_entry(
                        entry=q_feat["entry_price"],
                        stop=None,
                        day_bars=qqq_bars,
                        entry_end=end,
                        daily=daily.get(QQQ),
                        entry_day=entry_day,
                        forward_days=forward,
                    ),
                }
            )

    for sym in symbols:
        entry = open_entry(bars.get(sym), daily.get(sym), entry_day)
        if entry is None:
            continue
        leader_rows.append(
            {
                "symbol": sym,
                "window": OPEN_WINDOW,
                **outcome_for_entry(
                    entry=entry,
                    stop=None,
                    day_bars=bars.get(sym),
                    entry_end=None,
                    daily=daily.get(sym),
                    entry_day=entry_day,
                    forward_days=forward,
                ),
            }
        )
    q_entry = open_entry(qqq_bars, daily.get(QQQ), entry_day)
    if q_entry is not None:
        qqq_rows.append(
            {
                "symbol": QQQ,
                "window": OPEN_WINDOW,
                **outcome_for_entry(
                    entry=q_entry,
                    stop=None,
                    day_bars=qqq_bars,
                    entry_end=None,
                    daily=daily.get(QQQ),
                    entry_day=entry_day,
                    forward_days=forward,
                ),
            }
        )
    return rank_rows, leader_rows, qqq_rows


def snapshot_leaders(
    members,
    raw: dict[str, pd.DataFrame],
    splits: dict,
    themes,
    buy_dates: list[str],
    calendar: list[str],
    db_path: Path | None,
    *,
    force: bool = False,
) -> int:
    have = set() if force else leader_dates(db_path)
    todo = [day for day in buy_dates if day not in have]
    if not todo:
        _log(f"Leaders already stored for {len(buy_dates)} sessions")
        return 0
    _log(f"Scoring leaders for {len(todo)} sessions (point-in-time, prior close)")
    written = 0
    for i, day in enumerate(todo, start=1):
        rows = leaders_on(day, members, raw, splits, themes, calendar)
        replace_leaders(day, rows, db_path)
        written += 1
        if i == 1 or i == len(todo) or i % 10 == 0:
            _log(f"  [{i}/{len(todo)}] {day}: {len(rows)} leaders" + (f" ({rows[0]['symbol']})" if rows else ""))
    return written


def drop_sessions_that_never_opened(calendar: list[str], today: date, db_path: Path | None) -> None:
    live = set(calendar)
    for day in list(leader_dates(db_path)):
        if day < today.isoformat() and day not in live:
            delete_day(day, db_path)


def fetch_missing_bars(
    provider,
    wanted: set[tuple[str, str]],
    db_path: Path | None,
    *,
    today: date,
    clock: datetime | None = None,
) -> int:
    """Download raw bars for (symbol, date) pairs that are not stored and not a known gap."""
    if not wanted:
        _log("Intraday bars already cover the leader sessions in range")
        return 0
    covered = bar_coverage({s for s, _ in wanted}, min(d for _, d in wanted), max(d for _, d in wanted), db_path=db_path)
    gaps = gap_dates("15m", provider.name, db_path)
    missing: dict[str, set[str]] = {}
    for symbol, day in wanted:
        if (symbol, day) in covered or (symbol, day) in gaps:
            continue
        if not session_is_complete(day, today, clock):
            continue
        missing.setdefault(symbol, set()).add(day)
    if not missing:
        _log("No missing 15-minute bars inside the provider window")
        return 0
    start = date.fromisoformat(min(d for days in missing.values() for d in days))
    end = date.fromisoformat(max(d for days in missing.values() for d in days))
    symbols = sorted(missing)
    _log(f"Fetching 15-minute bars for {len(symbols)} symbols, {start} → {end}, via {provider.name}")
    fetched = provider.fetch(symbols, start, end)
    if not fetched:
        _log("Intraday provider returned nothing; leaving those sessions to retry")
        return 0
    saved = 0
    for symbol in symbols:
        frame = fetched.get(symbol)
        if frame is not None and not frame.empty:
            saved += save_bars(symbol, frame, "15m", provider.name, db_path)
            have = {ts.strftime("%Y-%m-%d") for ts in frame.index}
        else:
            have = set()
        for day in missing[symbol]:
            if day not in have:
                mark_gap(symbol, day, "15m", provider.name, db_path)
    _log(f"Stored {saved} intraday bars")
    return saved


def recompute_results(
    days: list[str],
    calendar: list[str],
    raw_daily: dict[str, pd.DataFrame],
    splits: dict,
    weights: IntervalWeights,
    db_path: Path | None,
    *,
    force: bool = False,
) -> int:
    if not days:
        return 0
    leaders = all_leaders(db_path)
    by_day: dict[str, list[str]] = {}
    for row in leaders:
        if row["date"] in set(days):
            by_day.setdefault(row["date"], []).append(row["symbol"])
    if not force:
        # Days with no results yet, and days whose +5 close was unknown and is knowable now.
        pending = incomplete_result_dates(calendar, db_path=db_path)
        days = [day for day in days if day in pending]
    if not days:
        _log("Entry results are already filled in")
        return 0
    symbols = sorted({sym for day in days for sym in by_day.get(day, [])} | {QQQ})
    if not symbols:
        return 0
    start, end = min(days), max(calendar)
    intraday = _adjust_frames(load_bars(symbols, start, end, db_path=db_path), splits, end)
    # Daily frames are already raw. Adjust through the last session so a split inside a hold is not a crash.
    daily = _adjust_frames(raw_daily, splits, calendar[-1] if calendar else end)
    _log(f"Computing check-in ranks and outcomes for {len(days)} sessions")
    written = 0
    for day in days:
        names = by_day.get(day, [])
        if not names:
            continue
        ranks, leader_rows, qqq_rows = compute_day(day, names, intraday, daily, calendar, weights)
        replace_ranks(day, ranks, db_path)
        replace_results(day, leader_rows, role="leader", db_path=db_path)
        replace_results(day, qqq_rows, role="benchmark", db_path=db_path)
        written += 1
    return written


def wanted_bars(db_path: Path | None, days: list[str]) -> set[tuple[str, str]]:
    wanted = set()
    for row in all_leaders(db_path):
        if row["date"] in set(days):
            wanted.add((row["symbol"], row["date"]))
            wanted.add((QQQ, row["date"]))
    return wanted


def _members_and_themes():
    from .members import effective_universe
    from .themes import ThemeError, load_themes
    from .universe import load_universe

    members = effective_universe(load_universe())
    try:
        themes = load_themes()
    except (OSError, ThemeError):
        themes = None
    return members, themes


def ensure_daily(members, db_path: Path | None = None) -> None:
    from .scheduler import history_due, now_et

    symbols = [m.symbol for m in members]
    cached = data.cached_symbols(db_path)
    missing = [s for s in symbols if s not in cached]
    if len(missing) > max(20, len(symbols) // 5):
        _log(f"Daily cache is missing {len(missing)} symbols; downloading history")
        data.refresh(symbols, full=True, progress=_progress, db_path=db_path)
    elif history_due(now_et(), data.newest_bar_date(db_path)):
        _log("Daily cache is behind the last session; downloading the gap")
        data.refresh(symbols, full=False, progress=_progress, db_path=db_path)


def _progress(done: int, total: int, message: str) -> None:
    _log(f"[{done}/{total}] {message}")


def run(
    *,
    months: int = 12,
    recompute: bool = False,
    force_leaders: bool = False,
    skip_bars: bool = False,
    provider_name: str | None = None,
    sessions: int | None = None,
    db_path: Path | None = None,
    refresh_daily: bool = True,
) -> dict:
    """Fill leader snapshots for ``months`` of sessions and bars as far as the provider allows.

    ``sessions`` limits the work to the last N completed sessions plus the upcoming one
    (the after-close job). ``recompute`` rebuilds outcomes even when the +5 day is already stored.
    """
    members, themes = _members_and_themes()
    if refresh_daily:
        ensure_daily(members, db_path)
    raw = data.load_all_daily(db_path, adjust=False)
    splits = data.load_splits(db_path)
    calendar = trading_calendar(raw)
    if len(calendar) < 2:
        _log("Not enough daily history to score a prior close")
        return {"leaders": 0, "bars": 0, "results": 0}
    today = today_et()
    drop_sessions_that_never_opened(calendar, today, db_path)
    buy_dates = dates_in_window(calendar, months, today)
    upcoming = upcoming_session(calendar, today)
    if upcoming:
        buy_dates = list(dict.fromkeys([*buy_dates, upcoming]))
    if sessions is not None:
        buy_dates = buy_dates[-sessions:]
    written = snapshot_leaders(members, raw, splits, themes, buy_dates, calendar, db_path, force=force_leaders)
    # Reload: a force rewrite clears results, and the upcoming day has no bar.
    completed = [day for day in buy_dates if session_is_complete(day, today)]
    saved = 0
    if not skip_bars and completed:
        provider = get_intraday_provider(provider_name)
        saved = fetch_missing_bars(provider, wanted_bars(db_path, completed), db_path, today=today)
    # Outcomes also need the forward daily bars, so pass the full calendar, not only buy_dates.
    result_days = completed if (recompute or sessions is None) else completed
    if sessions is not None and not recompute:
        result_days = completed
    updated = recompute_results(
        result_days, calendar, raw, splits, weights_from_env(), db_path, force=recompute
    )
    _log(f"Done. New leader sessions: {written}. Bars upserted: {saved}. Result sessions: {updated}.")
    return {"leaders": written, "bars": saved, "results": updated}


def collect_recent(sessions: int = 8, db_path: Path | None = None) -> dict:
    """After the close: the last few sessions, plus the next session's leader list. No full rescan."""
    return run(months=12, sessions=sessions, refresh_daily=False, db_path=db_path)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Collect morning leaders, 15-minute bars and entry results")
    parser.add_argument("--months", type=int, default=12, help="how many months of leader sessions to keep filled (default 12)")
    parser.add_argument("--sessions", type=int, default=None, help="only the last N sessions (the daily job)")
    parser.add_argument("--recompute", action="store_true", help="rebuild ranks and outcomes from stored bars")
    parser.add_argument("--force-leaders", action="store_true", help="rescan every session, ignoring stored snapshots")
    parser.add_argument("--skip-bars", action="store_true", help="do not call the intraday provider")
    parser.add_argument("--provider", default=None, help="yahoo (default) or alpaca")
    parser.add_argument("--no-refresh", action="store_true", help="do not download daily bars first")
    args = parser.parse_args(argv)
    run(
        months=args.months,
        recompute=args.recompute,
        force_leaders=args.force_leaders,
        skip_bars=args.skip_bars,
        provider_name=args.provider,
        sessions=args.sessions,
        refresh_daily=not args.no_refresh,
    )


if __name__ == "__main__":
    main()
