"""5-minute Strat pullback entry after a 20 RMA close, stopped at the low of day.

A top-10 leader qualifies on the first 5-minute bar of the session whose close is strictly above
the 20-period Wilder RMA. Earlier sessions warm the average and are not themselves the cross.
After that close, the name has to print a pullback: the bar before the trigger is a 2D or an
inside. The trigger is the first trade above that bar's high. A bar that opens above it fills at
the open; otherwise the fill is the prior high. The patterns are 2d-2u, 2d-1-2u, 3-1-2u,
1-2d-2u, and 1-2u. A 2U straight after a 3 is not one of them.

The earliest known-by time is 9:45. Two books cut the latest known-by time at 11:00 and at 10:30.
A through-trade is known at the bar's end. A gap fill is known at the bar's start, so the bar
that ends five minutes after the cutoff can still fill at its open. One trade per name per day.
The stop is the session low from 9:30 through the entry bar. The entry bar is not a stop. A later
bar at or below the stop exits at the stop. A bar that opens below the stop exits at the open.

Books keep the best leader-list rank, the best two, the best three, and every fill. Rank 1 is the
best prior-close score. They sit next to the 10:30 rank-tie books, which enter at the 10:30 close.
"""

from __future__ import annotations

from datetime import time
from typing import Mapping, Optional, Sequence

import pandas as pd

from .candles import INSIDE, OUTSIDE, TWO_DOWN, Candle, classify_series
from .morning import (
    BENCHMARK,
    HORIZONS,
    RMA_LENGTH,
    _horizon_done,
    _mean,
    _summarize_book,
    entry_at,
    lod_outcome,
    realized_lod_r,
    rma_rank_cap,
    session_low_through,
    window_end,
)

LENGTH = RMA_LENGTH
EARLIEST = time(9, 45)
CUTOFFS = ("11:00", "10:30")
# Fills whose known-by time is inside this window. The pullback bar itself may be earlier.
WINDOW = "win"
WINDOW_EARLIEST = time(10, 0)
WINDOW_LATEST = "10:30"
WINDOW_BOOKS: tuple[tuple[str, int, str, str, str], ...] = (
    ("win_time_first", 1, "time", "Time first", "10:00–10:30, first by time"),
    ("win_time_two", 2, "time", "Time first 2", "10:00–10:30, first 2 by time"),
    ("win_rank_first", 1, "rank", "Rank first", "10:00–10:30, first by rank"),
    ("win_rank_two", 2, "rank", "Rank first 2", "10:00–10:30, first 2 by rank"),
)
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
# (id suffix, cap or None, column label)
_CAPS = (("first", 1, "First"), ("two", 2, "First 2"), ("three", 3, "First 3"), ("all", None, "All"))
PULLBACK_BOOKS: tuple[tuple[str, str, Optional[int], str, str], ...] = tuple(
    (
        f"pb{cutoff.replace(':', '')}_{suffix}",
        cutoff,
        limit,
        f"{cutoff} {label.lower()}" if suffix != "all" else f"{cutoff} all",
        f"{cutoff} pullback, {label.lower()}" if suffix != "all" else f"{cutoff} pullback, all",
    )
    for cutoff in CUTOFFS
    for suffix, limit, label in _CAPS
)
# Columns in each panel, interleaved with the 10:30 rank-tie book of the same width.
PULLBACK_PANELS: tuple[dict, ...] = (
    {
        "title": "Pullback, in by 11:00",
        "books": ["pb1100_first", "pb1100_two", "pb1100_three", "pb1100_all"],
        "refs": ["rma_first_rank", "rma_two", "rma_three", "rma_all"],
    },
    {
        "title": "Pullback, in by 10:30",
        "books": ["pb1030_first", "pb1030_two", "pb1030_three", "pb1030_all"],
        "refs": ["rma_first_rank", "rma_two", "rma_three", "rma_all"],
    },
)


def pullback_text() -> str:
    return (
        "A top-10 leader qualifies when a 5-minute bar closes above the 20 RMA. After that, the "
        "next trade waits for a pullback, a 2D or an inside bar, and buys the first trade above "
        "that bar's high. The patterns are 2d-2u, 2d-1-2u, 3-1-2u, 1-2d-2u, and 1-2u. A bar that "
        "opens above the prior high fills at the open. The earliest fill is 9:45. One book stops "
        "taking new fills at 11:00 and one at 10:30. The stop is the low from 9:30 through the "
        "entry bar. One R is that distance. First, first 2, and first 3 are the best leader-list "
        "ranks among the names that filled, rank 1 ahead of rank 2. The columns beside them are "
        "the 10:30 rank-tie books, bought at the 10:30 close."
    )


def pullback_kind(types: Sequence[Optional[str]], i: int) -> Optional[str]:
    """Prefix of a pullback whose trigger bar is at ``i``. The trigger bar's own type is ignored."""
    if i < 1:
        return None
    prev = types[i - 1]
    before = types[i - 2] if i >= 2 else None
    if prev == INSIDE and before == TWO_DOWN:
        return "2d-1-2u"
    if prev == INSIDE and before == OUTSIDE:
        return "3-1-2u"
    if prev == INSIDE:
        return "1-2u"
    if prev == TWO_DOWN and before == INSIDE:
        return "1-2d-2u"
    if prev == TWO_DOWN:
        return "2d-2u"
    return None


def _rth(bars: Optional[pd.DataFrame]) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame()
    frame = bars[~bars.index.duplicated(keep="last")].sort_index()
    clock = frame.index.time
    return frame[(clock > SESSION_OPEN) & (clock <= SESSION_CLOSE)]


def prepare_pullbacks(
    intraday: Mapping[str, pd.DataFrame],
    symbols: Sequence[str],
    length: int = LENGTH,
) -> dict[str, tuple[pd.DataFrame, list]]:
    """RTH bars plus the RMA and Strat type of every bar, once per symbol."""
    from .morning import wilder_rma

    prepared: dict[str, tuple[pd.DataFrame, list]] = {}
    for sym in symbols:
        frame = _rth(intraday.get(sym))
        if frame.empty:
            continue
        values = wilder_rma([float(value) for value in frame["close"]], length)
        types = classify_series([
            Candle(float(row.open), float(row.high), float(row.low), float(row.close))
            for row in frame.itertuples()
        ])
        tagged = frame.copy()
        tagged["rma"] = values
        prepared[sym] = (tagged, types)
    return prepared


def _clock(stamp: pd.Timestamp) -> str:
    return pd.Timestamp(stamp).strftime("%H:%M")


def first_pullback(
    prepared: Optional[tuple[pd.DataFrame, Sequence]],
    day: str,
    cutoff: str,
    bars: Optional[pd.DataFrame] = None,
    length: int = LENGTH,
    earliest: time = EARLIEST,
    book: Optional[str] = None,
) -> Optional[dict]:
    """First pullback fill between ``earliest`` and ``cutoff``. None when the day does not fill.

    A trigger before ``earliest`` is skipped and the scan continues. ``bars`` is the raw frame used
    for the session low. ``prepared`` carries the RMA and types. ``book`` is the stored cutoff id
    when it is not the latest clock itself.
    """
    if prepared is None:
        return None
    frame, types = prepared
    if frame is None or frame.empty:
        return None
    day_ts = pd.Timestamp(day)
    positions = [i for i, ts in enumerate(frame.index) if pd.Timestamp(ts).normalize() == day_ts]
    if not positions:
        return None
    qualified = None
    for i in positions:
        rma = float(frame.iloc[i]["rma"])
        close = float(frame.iloc[i].close)
        if rma == rma and close > rma:
            qualified = i
            break
    if qualified is None:
        return None
    latest = time.fromisoformat(cutoff)
    for i in positions:
        # The pullback bar sits between the qualifying close and the trigger.
        if i < qualified + 2:
            continue
        kind = pullback_kind(types, i)
        if kind is None:
            continue
        if pd.Timestamp(frame.index[i - 1]).normalize() != day_ts:
            continue
        bar_end = pd.Timestamp(frame.index[i])
        bar_start = bar_end - pd.Timedelta(minutes=5)
        if bar_start.time() > latest:
            break
        opened = float(frame.iloc[i].open)
        high = float(frame.iloc[i].high)
        prior_high = float(frame.iloc[i - 1].high)
        if opened != opened or high != high or prior_high != prior_high:
            continue
        if opened > prior_high:
            entry = opened
            clock = bar_start
        elif high > prior_high:
            entry = prior_high
            clock = bar_end
        else:
            continue
        if clock.time() < earliest:
            continue
        if clock.time() > latest:
            break
        stop = session_low_through(bars if bars is not None else frame, bar_end)
        if stop is None or not (entry > 0 and stop < entry):
            continue
        return {
            "entry_price": entry,
            "stop_price": stop,
            "entry_time": _clock(clock),
            "entry_end": bar_end,
            "pattern": kind,
            "cutoff": book or cutoff,
        }
    return None


def _leader_rank(ranks: Optional[Mapping[str, int]], symbol: str) -> Optional[int]:
    if not ranks or symbol not in ranks:
        return None
    try:
        return int(ranks[symbol])
    except (TypeError, ValueError):
        return None


def pullbacks_for_day(
    day: str,
    symbols: Sequence[str],
    intraday: Mapping[str, pd.DataFrame],
    daily: Mapping[str, pd.DataFrame],
    calendar: Sequence[str],
    ranks: Optional[Mapping[str, int]] = None,
    prepared: Optional[Mapping[str, tuple]] = None,
    length: int = LENGTH,
) -> list[dict]:
    """Both cutoffs for the day's leaders, plus QQQ held from each fill's clock with no stop."""
    if prepared is None:
        prepared = prepare_pullbacks(intraday, symbols, length)
    forward = [pd.Timestamp(stamp) for stamp in calendar if stamp > day][:5]
    entry_day = pd.Timestamp(day)
    rows: list[dict] = []
    clocks: set[str] = set()
    for sym in symbols:
        bars = intraday.get(sym)
        found_by = {}
        scans = [(cutoff, EARLIEST, cutoff) for cutoff in CUTOFFS]
        scans.append((WINDOW_LATEST, WINDOW_EARLIEST, WINDOW))
        for latest, earliest, book in scans:
            found = first_pullback(
                prepared.get(sym), day, latest, bars, length, earliest=earliest, book=book,
            )
            if found is not None:
                found_by[book] = found
        for cutoff, found in found_by.items():
            outcome = lod_outcome(
                entry=found["entry_price"],
                stop=found["stop_price"],
                day_bars=bars,
                entry_end=found["entry_end"],
                daily=daily.get(sym),
                entry_day=entry_day,
                forward_days=forward,
            )
            rows.append({
                "date": day,
                "symbol": sym,
                "cutoff": cutoff,
                "entry_time": found["entry_time"],
                "pattern": found["pattern"],
                "rank": _leader_rank(ranks, sym),
                **outcome,
            })
            clocks.add(found["entry_time"])
    qqq_bars = intraday.get(BENCHMARK)
    for clock in sorted(clocks):
        end = window_end(day, clock)
        price = entry_at(qqq_bars, end)
        if price is None:
            continue
        rows.append({
            "date": day,
            "symbol": BENCHMARK,
            "cutoff": "qqq",
            "entry_time": clock,
            "pattern": None,
            "rank": None,
            **lod_outcome(
                entry=price,
                stop=None,
                day_bars=qqq_bars,
                entry_end=end,
                daily=daily.get(BENCHMARK),
                entry_day=entry_day,
                forward_days=forward,
            ),
        })
    return rows


def _rank_key(row: Mapping) -> tuple:
    rank = row.get("rank")
    try:
        rank_n = int(rank) if rank is not None else 10**9
    except (TypeError, ValueError):
        rank_n = 10**9
    return (rank_n, str(row.get("symbol") or ""))


def _time_key(row: Mapping) -> tuple:
    """Earliest trigger, then a better leader rank, then the symbol."""
    return (str(row.get("entry_time") or "99:99"), *_rank_key(row))


def _select(
    rows: Sequence[Mapping],
    cutoff: str,
    limit: Optional[int],
    key=None,
) -> list[Mapping]:
    chosen = [row for row in rows if row.get("cutoff") == cutoff]
    if limit is None:
        return chosen
    order = key or _rank_key
    grouped: dict[str, list] = {}
    for row in chosen:
        grouped.setdefault(str(row.get("date")), []).append(row)
    picked: list[Mapping] = []
    for group in grouped.values():
        picked.extend(sorted(group, key=order)[:limit])
    return picked


def _morning_buckets(rows: Sequence[Mapping], sessions: Optional[Sequence[str]]) -> dict:
    """How many mornings had 0, 1, 2, or 3+ of these fills. Tape days with none count as zero."""
    counts: dict[str, int] = {}
    for row in rows:
        day = str(row.get("date"))
        counts[day] = counts.get(day, 0) + 1
    base = [str(day) for day in sessions] if sessions is not None else sorted(counts)
    buckets = {"0": 0, "1": 0, "2": 0, "more": 0}
    for day in base:
        n = counts.get(day, 0)
        if n >= 3:
            buckets["more"] += 1
        else:
            buckets[str(n)] += 1
    return buckets


def _daily_avg_r(trades: Sequence[Mapping]) -> dict[str, dict[str, float]]:
    by_date: dict[str, list] = {}
    for trade in trades:
        by_date.setdefault(str(trade["date"]), []).append(trade)
    out = {name: {} for name, _, _ in HORIZONS}
    for day, group in by_date.items():
        for name, _idx, _field in HORIZONS:
            if not _horizon_done(group, name):
                continue
            values = [value for value in (realized_lod_r(row, name) for row in group) if value is not None]
            if values:
                out[name][day] = sum(values) / len(values)
    return out


def _risk_pair(rows: Sequence[Mapping], rma_rows: Sequence[Mapping]) -> dict:
    """Dollar risk, and how the fill compares with the 10:30 entry on the same name and day."""
    other = {
        (str(row.get("date")), str(row.get("symbol"))): row
        for row in rma_rows
        if row.get("rule") == "rma1030"
    }
    risks = []
    paired_rma = []
    saved = []
    for row in rows:
        entry = row.get("entry_price")
        stop = row.get("stop_price")
        if entry is None or stop is None:
            continue
        risks.append(float(entry) - float(stop))
        match = other.get((str(row.get("date")), str(row.get("symbol"))))
        if not match or match.get("entry_price") is None or match.get("stop_price") is None:
            continue
        rma_entry = float(match["entry_price"])
        paired_rma.append(rma_entry - float(match["stop_price"]))
        if rma_entry > 0:
            saved.append((rma_entry - float(entry)) / rma_entry * 100.0)
    return {
        "avg_risk_dollars": _mean(risks),
        "avg_rma_risk_dollars": _mean(paired_rma),
        "avg_entry_saved_pct": _mean(saved),
        "n_paired": len(saved),
    }


def build_pullback_stats(
    rows: Sequence[Mapping],
    rma_rows: Sequence[Mapping] = (),
    score_ranks: Optional[Mapping[str, Mapping[str, int]]] = None,
    tape_days: Optional[Sequence[str]] = None,
) -> dict:
    """Eight books, two cutoffs by four widths, each measured against the 10:30 rank-tie book."""
    qqq = {
        (str(row["date"]), str(row["entry_time"])): row
        for row in rows
        if row.get("cutoff") == "qqq"
    }
    leaders = [row for row in rows if row.get("cutoff") in CUTOFFS]
    sessions = [str(day) for day in tape_days] if tape_days is not None else None
    rank_first = rma_rank_cap(rma_rows, score_ranks, 1)
    rank_two = rma_rank_cap(rma_rows, score_ranks, 2)
    rank_daily = {"first": _daily_avg_r(rank_first), "two": _daily_avg_r(rank_two)}
    books = {}
    for book_id, cutoff, limit, label, title in PULLBACK_BOOKS:
        selected = _select(leaders, cutoff, limit)
        body = _summarize_book(selected, qqq)
        daily = _daily_avg_r(selected)
        for name, _idx, _field in HORIZONS:
            for key in ("first", "two"):
                both = [
                    daily[name][day] - rank_daily[key][name][day]
                    for day in daily[name]
                    if day in rank_daily[key][name]
                ]
                body["horizons"][name][f"vs_rank_{key}"] = _mean(both)
        counts: dict[str, int] = {}
        for row in selected:
            counts[str(row["date"])] = counts.get(str(row["date"]), 0) + 1
        if sessions:
            per_day = _mean([counts.get(day, 0) for day in sessions])
        else:
            per_day = (len(selected) / len(counts)) if counts else None
        body.update(_risk_pair(selected, rma_rows))
        body["id"] = book_id
        body["label"] = label
        body["title"] = title
        body["cutoff"] = cutoff
        body["trades_per_day"] = per_day
        body["tape_days"] = len(sessions) if sessions is not None else len(counts)
        books[book_id] = body

    ranked = []
    for index, (book_id, *_rest) in enumerate(PULLBACK_BOOKS):
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
            "vs_rank_first": block.get("vs_rank_first"),
        }
    bench = _summarize_book(rank_first, {})
    bench_two = _summarize_book(rank_two, {})
    window_rows = [row for row in rows if row.get("cutoff") == WINDOW]
    window_books = {}
    for book_id, limit, order_name, label, title in WINDOW_BOOKS:
        order = _time_key if order_name == "time" else _rank_key
        selected = _select(window_rows, WINDOW, limit, order)
        body = _summarize_book(selected, qqq)
        daily = _daily_avg_r(selected)
        for name, _idx, _field in HORIZONS:
            for key in ("first", "two"):
                both = [
                    daily[name][day] - rank_daily[key][name][day]
                    for day in daily[name]
                    if day in rank_daily[key][name]
                ]
                body["horizons"][name][f"vs_rank_{key}"] = _mean(both)
        counts: dict[str, int] = {}
        for row in selected:
            counts[str(row["date"])] = counts.get(str(row["date"]), 0) + 1
        if sessions:
            per_day = _mean([counts.get(day, 0) for day in sessions])
        else:
            per_day = (len(selected) / len(counts)) if counts else None
        body.update(_risk_pair(selected, rma_rows))
        body["id"] = book_id
        body["label"] = label
        body["title"] = title
        body["cutoff"] = WINDOW
        body["trades_per_day"] = per_day
        body["tape_days"] = len(sessions) if sessions is not None else len(counts)
        body["mornings"] = _morning_buckets(selected, sessions)
        window_books[book_id] = body
    window_ranked = []
    for index, (book_id, *_rest) in enumerate(WINDOW_BOOKS):
        block = window_books[book_id]["horizons"]["d3"]
        if not block["n_days"] or block["avg_r"] is None:
            continue
        window_ranked.append((block["avg_r"], block["n_days"], -index, book_id, block))
    window_best = None
    if window_ranked:
        window_ranked.sort(reverse=True)
        _avg, _days, _order, book_id, block = window_ranked[0]
        window_best = {
            "id": book_id,
            "label": window_books[book_id]["title"],
            "avg_r": block["avg_r"],
            "n_days": block["n_days"],
            "n_trades": block["n_trades"],
            "vs_rank_first": block.get("vs_rank_first"),
            "vs_rank_two": block.get("vs_rank_two"),
        }
    return {
        "books": books,
        "order": [book_id for book_id, *_rest in PULLBACK_BOOKS],
        "panels": [dict(panel) for panel in PULLBACK_PANELS],
        "best": best,
        "benchmark": {
            "first": {
                "label": "10:30 rank first",
                "avg_r": bench["horizons"]["d3"]["avg_r"],
                "n_days": bench["horizons"]["d3"]["n_days"],
                "n_trades": bench["horizons"]["d3"]["n_trades"],
            },
            "two": {
                "label": "10:30 rank first 2",
                "avg_r": bench_two["horizons"]["d3"]["avg_r"],
                "n_days": bench_two["horizons"]["d3"]["n_days"],
                "n_trades": bench_two["horizons"]["d3"]["n_trades"],
            },
        },
        "window": {
            "books": window_books,
            "order": [book_id for book_id, *_rest in WINDOW_BOOKS],
            "refs": ["rma_first_rank", "rma_two"],
            "definition": window_text(),
            "best": window_best,
            "triggers": _morning_buckets(window_rows, sessions),
        },
    }


def window_text() -> str:
    return (
        "The same pullback, with the fill kept only when its time is from 10:00 through 10:30. "
        "A pullback bar can print before 10:00. A trigger before 10:00 is skipped, and the scan "
        "keeps looking for the next one inside the window. One trade per name. Time first and "
        "time first 2 take the earliest fills. A tie breaks by leader rank, then the symbol. "
        "Rank first and rank first 2 take the best leader-list ranks among the names that triggered "
        "in the window. The last two columns are the 10:30 rank-tie books, bought at the 10:30 close."
    )
