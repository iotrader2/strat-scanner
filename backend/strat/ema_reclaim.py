"""Buy a top-10 leader when it closes back above the 20 EMA after closing below it today.

The EMA is TradingView ``ta.ema`` (SMA seed, then ``alpha = 2 / (length + 1)``). Earlier sessions
warm it and are not themselves a pullback. During today's regular session the name must first have
a 5-minute bar whose close is strictly below the EMA, then a later bar whose close is strictly
back above it. That second bar is the entry, and it has to end at 9:45 or later. A close back
above before 9:45 does not fill: the pullback is over, and the next trade needs a fresh close
below. A name that never closes below the EMA, including one that opens above it and stays there,
is not bought. One reclaim per name per day.

The same entry is stopped three ways. The reclaim stop is that entry bar's low. The pullback stop
is the lowest low from the first close-below bar of that episode through the reclaim bar,
inclusive. The low-of-day stop is the session low from 9:30 through the entry bar. One R is the
distance from the entry down to that stop. A stop that is not strictly under the entry is dropped
for that variant only; the scan does not look for a later reclaim. The entry bar is not a stop.
A later bar at or below the stop exits at the stop. A bar that opens below the stop exits at the
open. Each stop is reported for every qualifying name and for the first one, two, and three names
that day. The order is the reclaim time, then the leader-list rank (1 is the best score),
then the symbol. A name inside the cap keeps its slot when one stop does not sit under the entry.
"""

from __future__ import annotations

from datetime import time
from typing import Mapping, Optional, Sequence

import pandas as pd

from .morning import (
    BENCHMARK,
    EMA_LENGTH,
    HORIZONS,
    _horizon_done,
    _mean,
    _summarize_book,
    ema,
    entry_at,
    lod_outcome,
    realized_lod_r,
    window_end,
)

EARLIEST = time(9, 45)
LENGTH = EMA_LENGTH
STOPS = ("reclaim", "pullback", "lod")
# (id, stored rule, cap or None for every name, column label, sentence title)
RECLAIM_BOOKS: tuple[tuple[str, str, Optional[int], str, str], ...] = (
    ("reclaim_first", "reclaim", 1, "First", "Reclaim bar, first"),
    ("reclaim_two", "reclaim", 2, "First 2", "Reclaim bar, first 2"),
    ("reclaim_three", "reclaim", 3, "First 3", "Reclaim bar, first 3"),
    ("reclaim_all", "reclaim", None, "All", "Reclaim bar, all"),
    ("pullback_first", "pullback", 1, "First", "Pullback low, first"),
    ("pullback_two", "pullback", 2, "First 2", "Pullback low, first 2"),
    ("pullback_three", "pullback", 3, "First 3", "Pullback low, first 3"),
    ("pullback_all", "pullback", None, "All", "Pullback low, all"),
    ("lod_first", "lod", 1, "First", "Low of day, first"),
    ("lod_two", "lod", 2, "First 2", "Low of day, first 2"),
    ("lod_three", "lod", 3, "First 3", "Low of day, first 3"),
    ("lod_all", "lod", None, "All", "Low of day, all"),
)
RECLAIM_PANELS: tuple[dict, ...] = (
    {"title": "Stop at the reclaim bar's low", "books": ["reclaim_first", "reclaim_two", "reclaim_three", "reclaim_all"]},
    {"title": "Stop at the pullback low", "books": ["pullback_first", "pullback_two", "pullback_three", "pullback_all"]},
    {"title": "Stop at the low of day", "books": ["lod_first", "lod_two", "lod_three", "lod_all"]},
)


def reclaim_text() -> str:
    return (
        "Every top-10 leader is bought at the close of the first 5-minute bar, from 9:45 on, that "
        "closes back above the 20 EMA after a bar in today's session closed below it. Earlier "
        "sessions warm the average. A close back above before 9:45 does not fill, and the name has "
        "to close below the EMA again. A name that never closes below it, including one that opened "
        "above and stayed there, is not bought. One trade per name. The same entry is stopped three "
        "ways: the reclaim bar's low, the lowest low from the first close below through that bar, "
        "and the session low from 9:30 through the entry. Each stop is shown for the first name, "
        "the first two, the first three, and every name. The order is the reclaim time, then the "
        "leader-list rank, with rank 1 ahead of rank 2."
    )


def _session(bars: pd.DataFrame, day: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prior bars, then today's regular-session bars. Premarket and after-hours prints are dropped."""
    start = pd.Timestamp(day)
    frame = bars.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    prior = frame.loc[frame.index < start]
    today = frame.loc[(frame.index >= start) & (frame.index < start + pd.Timedelta(days=1))]
    if today.empty:
        return prior, today
    minutes = today.index.hour * 60 + today.index.minute
    today = today[(minutes > 9 * 60 + 30) & (minutes <= 16 * 60)]
    return prior, today


def _under_entry(entry: float, stop: Optional[float]) -> Optional[float]:
    if stop is None or stop != stop or entry <= stop:
        return None
    return float(stop)


def first_reclaim(
    bars: Optional[pd.DataFrame],
    day: str,
    length: int = LENGTH,
    earliest: time = EARLIEST,
) -> Optional[dict]:
    """First close back above the EMA at or after 9:45, following a close below it today.

    None when the average is not ready, the name never closes below it, or the only reclaim is
    before 9:45. Stops that are not strictly under the entry are None. The pullback low includes
    the reclaim bar. An earlier reclaim before 9:45 ends that episode.
    """
    if bars is None or bars.empty:
        return None
    prior, today = _session(bars, day)
    if today.empty:
        return None
    prior_closes = [float(value) for value in prior["close"]] if not prior.empty else []
    today_closes = [float(value) for value in today["close"]]
    values = ema(prior_closes + today_closes, length)
    offset = len(prior_closes)
    in_pullback = False
    pull_low: Optional[float] = None
    lod: Optional[float] = None
    for i, ts in enumerate(today.index):
        stamp = pd.Timestamp(ts)
        average = values[offset + i]
        close = float(today.iloc[i].close)
        low = float(today.iloc[i].low)
        if low == low:
            lod = low if lod is None else min(lod, low)
        if average != average or close != close:
            continue
        if in_pullback and low == low:
            pull_low = low if pull_low is None else min(pull_low, low)
        if close < average:
            if not in_pullback:
                in_pullback = True
                pull_low = low if low == low else None
            continue
        if close > average and in_pullback and close > 0:
            if stamp.time() < earliest:
                in_pullback = False
                pull_low = None
                continue
            return {
                "entry_time": stamp.strftime("%H:%M"),
                "entry_price": close,
                "entry_end": stamp,
                "reclaim_stop": _under_entry(close, low if low == low else None),
                "pullback_stop": _under_entry(close, pull_low),
                "lod_stop": _under_entry(close, lod),
            }
    return None


def ema_reclaims_for_day(
    day: str,
    symbols: Sequence[str],
    intraday: Mapping[str, pd.DataFrame],
    daily: Mapping[str, pd.DataFrame],
    calendar: Sequence[str],
    length: int = LENGTH,
    ranks: Optional[Mapping[str, int]] = None,
) -> list[dict]:
    """One row per stop that sits under the entry, plus QQQ from each fill's clock."""
    forward = [pd.Timestamp(d) for d in calendar if d > day][:5]
    entry_day = pd.Timestamp(day)
    rows: list[dict] = []
    clocks: set[str] = set()
    for sym in symbols:
        signal = first_reclaim(intraday.get(sym), day, length)
        if signal is None:
            continue
        filled = False
        for rule in STOPS:
            stop = signal[f"{rule}_stop"]
            if stop is None:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "rule": rule,
                    "entry_time": signal["entry_time"],
                    "rank": None if ranks is None else ranks.get(sym),
                    **lod_outcome(
                        entry=signal["entry_price"],
                        stop=stop,
                        day_bars=intraday.get(sym),
                        entry_end=signal["entry_end"],
                        daily=daily.get(sym),
                        entry_day=entry_day,
                        forward_days=forward,
                    ),
                }
            )
            filled = True
        if filled:
            clocks.add(signal["entry_time"])
    qqq_bars = intraday.get(BENCHMARK)
    for clock in sorted(clocks):
        end = window_end(day, clock)
        price = entry_at(qqq_bars, end)
        if price is None:
            continue
        rows.append(
            {
                "symbol": BENCHMARK,
                "rule": "qqq",
                "entry_time": clock,
                **lod_outcome(
                    entry=price,
                    stop=None,
                    day_bars=qqq_bars,
                    entry_end=end,
                    daily=daily.get(BENCHMARK),
                    entry_day=entry_day,
                    forward_days=forward,
                ),
            }
        )
    return rows


def _daily_avg_r(trades: Sequence[Mapping]) -> dict[str, dict[str, float]]:
    by_date: dict[str, list[Mapping]] = {}
    for trade in trades:
        by_date.setdefault(str(trade["date"]), []).append(trade)
    out = {name: {} for name, _, _ in HORIZONS}
    for day, rows in by_date.items():
        for name, _idx, _field in HORIZONS:
            if not _horizon_done(rows, name):
                continue
            values = [realized_lod_r(row, name) for row in rows]
            ready = [value for value in values if value is not None]
            if ready:
                out[name][day] = sum(ready) / len(ready)
    return out


def _order_key(row: Mapping) -> tuple:
    """Earlier reclaim, then a better leader-list rank, then the symbol."""
    rank = row.get("rank")
    try:
        rank_n = int(rank) if rank is not None else 10**9
    except (TypeError, ValueError):
        rank_n = 10**9
    return (str(row.get("entry_time") or ""), rank_n, str(row.get("symbol") or ""))


def _capped_symbols(rows: Sequence[Mapping], limit: int) -> dict[str, set[str]]:
    """First ``limit`` symbols that reclaimed, shared by every stop.

    A name that triggered keeps its place even when one stop is not under the entry, so a later
    name does not move up to fill that stop's book.
    """
    seen: dict[tuple[str, str], Mapping] = {}
    for row in rows:
        if row.get("rule") not in STOPS:
            continue
        key = (str(row["date"]), str(row["symbol"]))
        current = seen.get(key)
        if current is None or _order_key(row) < _order_key(current):
            seen[key] = row
    by_day: dict[str, list[Mapping]] = {}
    for (day, _symbol), row in seen.items():
        by_day.setdefault(day, []).append(row)
    allowed: dict[str, set[str]] = {}
    for day, group in by_day.items():
        group.sort(key=_order_key)
        allowed[day] = {str(row["symbol"]) for row in group[:limit]}
    return allowed


def _select(rows: Sequence[Mapping], rule: str, limit: Optional[int]) -> list[Mapping]:
    chosen = [row for row in rows if row.get("rule") == rule]
    if limit is None:
        return chosen
    allowed = _capped_symbols(rows, limit)
    return [row for row in chosen if str(row["symbol"]) in allowed.get(str(row["date"]), ())]


def build_reclaim_stats(
    leader_rows: Sequence[Mapping],
    qqq_rows: Sequence[Mapping],
    rma_first_rows: Sequence[Mapping] = (),
    tape_days: Optional[Sequence[str]] = None,
) -> dict:
    """Twelve books. The cap is the first 1, 2, or 3 reclaims. Trades per day includes quiet tape sessions."""
    qqq = {(str(row["date"]), str(row["entry_time"])): row for row in qqq_rows}
    rma_daily = _daily_avg_r(rma_first_rows)
    sessions = [str(day) for day in tape_days] if tape_days is not None else None
    books = {}
    for book_id, rule, limit, label, title in RECLAIM_BOOKS:
        rows = _select(leader_rows, rule, limit)
        body = _summarize_book(rows, qqq)
        daily = _daily_avg_r(rows)
        for name, _idx, _field in HORIZONS:
            both = [daily[name][day] - rma_daily[name][day] for day in daily[name] if day in rma_daily[name]]
            body["horizons"][name]["vs_rma_first"] = _mean(both)
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row["date"])] = counts.get(str(row["date"]), 0) + 1
        if sessions:
            per_day = _mean([counts.get(day, 0) for day in sessions])
        else:
            per_day = (len(rows) / len(counts)) if counts else None
        body["id"] = book_id
        body["label"] = label
        body["title"] = title
        body["rule"] = rule
        body["trades_per_day"] = per_day
        body["tape_days"] = len(sessions) if sessions is not None else len(counts)
        books[book_id] = body

    ranked = []
    for index, (book_id, *_rest) in enumerate(RECLAIM_BOOKS):
        block = books[book_id]["horizons"]["d3"]
        if not block["n_days"] or block["avg_r"] is None:
            continue
        ranked.append((block["avg_r"], block["n_days"], -index, book_id, block))
    best = None
    if ranked:
        ranked.sort(reverse=True)
        _avg, _days, _order, book_id, block = ranked[0]
        best = {
            "id": book_id,
            "label": books[book_id]["title"],
            "avg_r": block["avg_r"],
            "n_days": block["n_days"],
            "n_trades": block["n_trades"],
            "vs_rma_first": block.get("vs_rma_first"),
        }
    benchmark = None
    if rma_first_rows:
        packed = _summarize_book(list(rma_first_rows), {})
        block = packed["horizons"]["d3"]
        if block["n_days"] and block["avg_r"] is not None:
            benchmark = {"label": "10:30 first", "avg_r": block["avg_r"], "n_days": block["n_days"], "n_trades": block["n_trades"]}
    return {
        "books": books,
        "order": [book_id for book_id, *_rest in RECLAIM_BOOKS],
        "panels": [dict(panel) for panel in RECLAIM_PANELS],
        "best": best,
        "benchmark": benchmark,
    }
