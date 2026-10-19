"""Buy every top-10 leader at the first 5-minute close, from 9:45 on, that is above a 20-period average.

The same rule runs three times: Wilder RMA (TradingView ``ta.rma``), a simple moving average, and
an EMA (TradingView ``ta.ema``). Earlier sessions warm the average. A bar that ends before 9:45
cannot be the entry, even when its close is already above the average. Close must be strictly above.

A name that opens above the average is not skipped and is not required to cross up from below.
Its entry is still the first bar at or after 9:45 that closes above the average. "Opened above"
means the open of the first regular-session bar (the 9:30 print) is strictly above the average
carried in from the prior session, before today's bars update it. Those fills are counted.

The entry is that bar's close. The stop is that same bar's low, which is final once the bar has
closed. One R is that distance. The entry bar is not a stop. A later bar at or below the stop
exits at the stop; a bar that opens below it exits at the open. A bar whose low is not strictly
under its close has no risk and is skipped, and the scan keeps looking for a later bar that day.
One trade per name per average per day. A name that never closes above the average is not bought.
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
    wilder_rma,
    window_end,
)

EARLIEST = time(9, 45)
LENGTH = EMA_LENGTH
KINDS = ("rma", "sma", "ema")
# (id, stored rule, label)
CROSS_BOOKS: tuple[tuple[str, str, str], ...] = (
    ("rma", "rma", "RMA"),
    ("sma", "sma", "SMA"),
    ("ema", "ema", "EMA"),
)


def cross_text() -> str:
    return (
        "Every top-10 leader is bought at the close of the first 5-minute bar, from 9:45 on, that "
        "closes strictly above its 20-period average. Earlier sessions warm the average. Nothing "
        "before 9:45 is an entry. A name that opens above the average is included: the open of the "
        "first bar (the 9:30 print) is compared with the average from the prior session, and those "
        "fills are counted. The stop is that entry bar's low. One R is that distance. The same rule "
        "runs on the Wilder RMA, the 20 SMA, and the 20 EMA."
    )


def sma(closes: Sequence[float], length: int = LENGTH) -> list[float]:
    """TradingView ``ta.sma``: the mean of the last ``length`` closes. Earlier values are NaN."""
    n = len(closes)
    out = [float("nan")] * n
    if n < length or length < 1:
        return out
    total = sum(closes[:length])
    out[length - 1] = total / length
    for i in range(length, n):
        total += closes[i] - closes[i - length]
        out[i] = total / length
    return out


def moving_average(closes: Sequence[float], kind: str, length: int = LENGTH) -> list[float]:
    if kind == "rma":
        return wilder_rma(closes, length)
    if kind == "sma":
        return sma(closes, length)
    if kind == "ema":
        return ema(closes, length)
    raise ValueError(kind)


def _last_ready(values: Sequence[float]) -> Optional[float]:
    for value in reversed(values):
        if value == value:
            return float(value)
    return None


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


def first_cross(
    bars: Optional[pd.DataFrame],
    day: str,
    kind: str,
    length: int = LENGTH,
    earliest: time = EARLIEST,
) -> Optional[dict]:
    """First bar of ``day`` at or after 9:45 whose close is strictly above the average.

    None when the average is not ready, no bar closes above it, or every such bar has no risk
    (its low is not under its close).
    """
    if bars is None or bars.empty:
        return None
    prior, today = _session(bars, day)
    if today.empty:
        return None
    prior_closes = [float(value) for value in prior["close"]] if not prior.empty else []
    today_closes = [float(value) for value in today["close"]]
    values = moving_average(prior_closes + today_closes, kind, length)
    carried = _last_ready(moving_average(prior_closes, kind, length)) if prior_closes else None
    first_open = float(today.iloc[0].open)
    opened_above = int(carried is not None and first_open == first_open and first_open > carried)
    offset = len(prior_closes)
    for i, ts in enumerate(today.index):
        stamp = pd.Timestamp(ts)
        if stamp.time() < earliest:
            continue
        average = values[offset + i]
        close = float(today.iloc[i].close)
        low = float(today.iloc[i].low)
        if average != average or close != close or low != low:
            continue
        if close <= average or close <= 0 or low >= close:
            continue
        return {
            "rule": kind,
            "entry_time": stamp.strftime("%H:%M"),
            "entry_price": close,
            "stop_price": low,
            "entry_end": stamp,
            "opened_above": opened_above,
        }
    return None


def cross_triggers_for_day(
    day: str,
    symbols: Sequence[str],
    intraday: Mapping[str, pd.DataFrame],
    daily: Mapping[str, pd.DataFrame],
    calendar: Sequence[str],
) -> list[dict]:
    """RMA, SMA, and EMA triggers for the day's leaders, plus QQQ from each fill's clock."""
    forward = [pd.Timestamp(d) for d in calendar if d > day][:5]
    entry_day = pd.Timestamp(day)
    rows: list[dict] = []
    clocks: set[str] = set()
    for kind in KINDS:
        for sym in symbols:
            signal = first_cross(intraday.get(sym), day, kind)
            if signal is None:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "rule": kind,
                    "entry_time": signal["entry_time"],
                    "opened_above": signal["opened_above"],
                    **lod_outcome(
                        entry=signal["entry_price"],
                        stop=signal["stop_price"],
                        day_bars=intraday.get(sym),
                        entry_end=signal["entry_end"],
                        daily=daily.get(sym),
                        entry_day=entry_day,
                        forward_days=forward,
                    ),
                }
            )
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
                "opened_above": 0,
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


def build_cross_stats(
    leader_rows: Sequence[Mapping],
    qqq_rows: Sequence[Mapping],
    rma_first_rows: Sequence[Mapping] = (),
    tape_days: Optional[Sequence[str]] = None,
) -> dict:
    """Three books. Trades per day includes tape sessions where nobody triggered."""
    qqq = {(str(row["date"]), str(row["entry_time"])): row for row in qqq_rows}
    rma_daily = _daily_avg_r(rma_first_rows)
    sessions = [str(day) for day in tape_days] if tape_days is not None else None
    books = {}
    for book_id, rule, label in CROSS_BOOKS:
        rows = [row for row in leader_rows if row.get("rule") == rule]
        body = _summarize_book(rows, qqq)
        daily = _daily_avg_r(rows)
        for name, _idx, _field in HORIZONS:
            both = [daily[name][day] - rma_daily[name][day] for day in daily[name] if day in rma_daily[name]]
            body["horizons"][name]["vs_rma_first"] = _mean(both)
        opened = sum(int(row.get("opened_above") or 0) for row in rows)
        counts: dict[str, int] = {}
        for row in rows:
            counts[str(row["date"])] = counts.get(str(row["date"]), 0) + 1
        if sessions:
            per_day = _mean([counts.get(day, 0) for day in sessions])
        else:
            per_day = (len(rows) / len(counts)) if counts else None
        body["id"] = book_id
        body["label"] = label
        body["rule"] = rule
        body["opened_above"] = opened
        body["opened_above_rate"] = (opened / len(rows)) if rows else None
        body["trades_per_day"] = per_day
        body["tape_days"] = len(sessions) if sessions is not None else len(counts)
        books[book_id] = body

    ranked = []
    for index, (book_id, *_rest) in enumerate(CROSS_BOOKS):
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
            "label": books[book_id]["label"],
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
        "order": [book_id for book_id, *_rest in CROSS_BOOKS],
        "best": best,
        "benchmark": benchmark,
    }
