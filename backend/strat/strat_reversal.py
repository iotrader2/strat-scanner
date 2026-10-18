"""15-minute and 30-minute Strat reversal entries, built from stored 5-minute bars.

Candles are session-aligned from 9:30 ET. The opening candle of the session is context only
(15-minute 9:30–9:45, 30-minute 9:30–10:00), so the earliest fill is 9:45 or 10:00.

Bullish reversals follow ``find_long_setups``: 2d-2u, 2d-1-2u, 3-1-2u, and 1-2d-2u.
A 2U after a 3, with no inside bar between them, is not a reversal there, so 3-2u is not used.
A 2D whose candle before that is an inside is 1-2d-2u and not also 2d-2u. A 2D with anything
else before it, including a 3 or no candle, is 2d-2u.

Entry is the first trade above the prior candle's high, timed on the 5-minute bars, without
waiting for the entry candle to close. A bar that opens above that high fills at its open.
The trade is kept even when the completed candle finishes as a 3. The label is the prefix.

The stop is fixed at the trigger: the lower of the prior candle's low and the lows of the
5-minute bars in the entry candle that had already closed. The trigger bar's low is not in
the stop, because the order inside that bar is unknown. The stop is not trailed to the
entry candle's final low. Hits are tracked only on 5-minute bars after the trigger bar.
A trigger whose stop is not strictly below the entry is skipped, and the scan keeps looking
for a later reversal that day. Nothing with a known-by time after 15:30.
"""

from __future__ import annotations

import math
from datetime import time
from typing import Mapping, Optional, Sequence

import pandas as pd

from .candles import INSIDE, OUTSIDE, TWO_DOWN, TWO_UP, Candle, classify_series
from .morning import (
    BENCHMARK,
    HORIZONS,
    _horizon_done,
    _mean,
    _summarize_book,
    cross_through,
    entry_at,
    lod_outcome,
    realized_lod_r,
    window_end,
)

SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)
LATEST_ENTRY = time(15, 30)
TIMEFRAMES = (15, 30)
# The opening candle has closed by this time. Entry candles start at or after it.
EARLIEST_START = {15: time(9, 45), 30: time(10, 0)}
PATTERNS = ("2d-2u", "2d-1-2u", "3-1-2u", "1-2d-2u")
# (id, minutes, RMA only, first name only, column label, sentence title)
STRAT_BOOKS: tuple[tuple[str, int, bool, bool, str, str], ...] = (
    ("15_all", 15, False, False, "All", "15-minute all"),
    ("15_first", 15, False, True, "First", "15-minute first"),
    ("15_rma_all", 15, True, False, "RMA all", "15-minute RMA all"),
    ("15_rma_first", 15, True, True, "RMA first", "15-minute RMA first"),
    ("30_all", 30, False, False, "All", "30-minute all"),
    ("30_first", 30, False, True, "First", "30-minute first"),
    ("30_rma_all", 30, True, False, "RMA all", "30-minute RMA all"),
    ("30_rma_first", 30, True, True, "RMA first", "30-minute RMA first"),
)


class AggCandle:
    """One session-aligned candle and the 5-minute bars it was built from."""

    def __init__(self, start: pd.Timestamp, end: pd.Timestamp, bars: pd.DataFrame):
        self.start = start
        self.end = end
        self.open = float(bars.iloc[0].open)
        self.high = float(bars["high"].max())
        self.low = float(bars["low"].min())
        self.close = float(bars.iloc[-1].close)
        self.bars = bars


class _PastCutoff:
    """A fill from here on would be after 15:30, and later bars are later still."""


_PAST_CUTOFF = _PastCutoff()


def reversal_text() -> str:
    return (
        "Bullish reversals are 2d-2u, 2d-1-2u, 3-1-2u, and 1-2d-2u, the same four this repo "
        "treats as reversals. 3-2u is not one of them, so it is not used. 15-minute and 30-minute "
        "candles are built from the stored 5-minute bars, aligned to 9:30. The opening candle is "
        "context only, so the earliest entry is 9:45 on the 15-minute chart and 10:00 on the "
        "30-minute chart. Entry is the first trade above the prior candle's high. A 5-minute bar "
        "that opens above that high fills at its open. The stop is the lower of the prior candle's "
        "low and the entry candle's low so far, excluding the trigger bar, and it stays there. "
        "Hits are tracked only after the entry. One R is that distance. The RMA books keep a name "
        "only when a 5-minute bar had closed above the 20 RMA by the decision time. First name is "
        "the earliest entry that day, then the symbol. Nothing after 15:30."
    )


def reversal_kind(types: Sequence[Optional[str]], i: int) -> Optional[str]:
    """Prefix of a bullish reversal whose entry candle is at ``i``. The entry candle's own type is ignored."""
    if i < 1:
        return None
    prev = types[i - 1]
    before = types[i - 2] if i >= 2 else None
    if prev == INSIDE and before == TWO_DOWN:
        return "2d-1-2u"
    if prev == INSIDE and before == OUTSIDE:
        return "3-1-2u"
    if prev == TWO_DOWN and before == INSIDE:
        return "1-2d-2u"
    if prev == TWO_DOWN:
        return "2d-2u"
    return None


def _bucket_end(bar_end: pd.Timestamp, minutes: int) -> pd.Timestamp:
    """End of the session candle that owns a 5-minute bar. 9:35 belongs to the 9:45 candle on a 15-minute chart."""
    open_ts = bar_end.normalize() + pd.Timedelta(hours=9, minutes=30)
    elapsed = int(round((bar_end - open_ts).total_seconds() / 60.0))
    buckets = max(1, math.ceil(elapsed / minutes))
    end = open_ts + pd.Timedelta(minutes=buckets * minutes)
    close = bar_end.normalize() + pd.Timedelta(hours=16)
    return close if end > close else end


def aggregate_bars(bars: Optional[pd.DataFrame], minutes: int) -> list[AggCandle]:
    """Full candles only. A 15-minute candle needs its three 5-minute bars, a 30-minute candle its six."""
    if bars is None or bars.empty or minutes not in TIMEFRAMES:
        return []
    frame = bars[~bars.index.duplicated(keep="last")].sort_index()
    grouped: dict[pd.Timestamp, list[pd.Timestamp]] = {}
    for ts in frame.index:
        stamp = pd.Timestamp(ts)
        clock = stamp.time()
        if clock <= SESSION_OPEN or clock > SESSION_CLOSE:
            continue
        grouped.setdefault(_bucket_end(stamp, minutes), []).append(stamp)
    need = minutes // 5
    out: list[AggCandle] = []
    for end in sorted(grouped):
        stamps = grouped[end]
        first = end - pd.Timedelta(minutes=minutes - 5)
        expected = [first + pd.Timedelta(minutes=5 * i) for i in range(need)]
        if stamps != expected:
            continue
        chunk = frame.loc[expected]
        out.append(AggCandle(end - pd.Timedelta(minutes=minutes), end, chunk))
    return out


def _hhmm(stamp: pd.Timestamp) -> str:
    return pd.Timestamp(stamp).strftime("%H:%M")


def _scan_trigger(candle: AggCandle, prior: AggCandle):
    """First in-bar break of the prior high at or before 15:30 whose stop is under the entry.

    Returns the fill, None when this candle never triggers, or ``_PAST_CUTOFF`` when a later
    bar could only fill after 15:30.
    """
    prior_high = prior.high
    prior_low = prior.low
    lows_before: list[float] = []
    for row in candle.bars.itertuples():
        bar_end = pd.Timestamp(row.Index)
        bar_start = bar_end - pd.Timedelta(minutes=5)
        opened = float(row.open)
        high = float(row.high)
        low = float(row.low)
        if opened != opened or high != high or low != low:
            continue
        if bar_start.time() > LATEST_ENTRY:
            return _PAST_CUTOFF
        if opened > prior_high:
            entry = opened
            clock = bar_start
            decision = bar_start
        elif high > prior_high:
            entry = prior_high
            clock = bar_end
            decision = bar_end
        else:
            lows_before.append(low)
            continue
        if clock.time() > LATEST_ENTRY:
            return _PAST_CUTOFF
        stop = min([prior_low, *lows_before]) if lows_before else prior_low
        if entry > 0 and stop < entry:
            return {
                "entry_price": entry,
                "stop_price": stop,
                "entry_time": _hhmm(clock),
                "entry_end": bar_end,
                "decision_end": decision,
            }
        # This bar has now closed, so a later trigger in the candle can see its low.
        lows_before.append(low)
    return None


def first_reversal(
    bars: Optional[pd.DataFrame],
    day: str,
    minutes: int,
    candles: Optional[Sequence[AggCandle]] = None,
) -> Optional[dict]:
    """The first valid reversal for one name on one session. None when the day has no fill.

    ``candles`` is the already-aggregated series for this symbol. Passing it avoids rebuilding
    the same candles once per session during a recompute.
    """
    if candles is None:
        candles = aggregate_bars(bars, minutes)
    if len(candles) < 2:
        return None
    types = classify_series([Candle(c.open, c.high, c.low, c.close) for c in candles])
    earliest = EARLIEST_START[minutes]
    day_ts = pd.Timestamp(day)
    for i, candle in enumerate(candles):
        if candle.end.normalize() != day_ts:
            continue
        if candle.start.time() < earliest:
            continue
        if candle.start.time() > LATEST_ENTRY:
            return None
        kind = reversal_kind(types, i)
        if kind is None:
            continue
        found = _scan_trigger(candle, candles[i - 1])
        if found is _PAST_CUTOFF:
            return None
        if found is None:
            continue
        return {
            **found,
            "pattern": kind,
            "finished_2u": int(types[i] == TWO_UP),
            "qualified": int(cross_through(bars, found["decision_end"]) is not None),
            "timeframe": minutes,
        }
    return None


def prepare_candles(
    intraday: Mapping[str, pd.DataFrame],
    symbols: Sequence[str],
) -> dict[tuple[str, int], list[AggCandle]]:
    """Aggregate each symbol once. The day loop then only scans the session it is scoring."""
    prepared: dict[tuple[str, int], list[AggCandle]] = {}
    for sym in symbols:
        frame = intraday.get(sym)
        for minutes in TIMEFRAMES:
            prepared[(sym, minutes)] = aggregate_bars(frame, minutes)
    return prepared


def strat_reversals_for_day(
    day: str,
    symbols: Sequence[str],
    intraday: Mapping[str, pd.DataFrame],
    daily: Mapping[str, pd.DataFrame],
    calendar: Sequence[str],
    prepared: Optional[Mapping[tuple[str, int], Sequence[AggCandle]]] = None,
) -> list[dict]:
    """Both timeframes for the day's leaders, plus QQQ held from each fill's clock with no stop."""
    forward = [pd.Timestamp(d) for d in calendar if d > day][:5]
    entry_day = pd.Timestamp(day)
    rows: list[dict] = []
    clocks: set[str] = set()
    for minutes in TIMEFRAMES:
        for sym in symbols:
            cached = None if prepared is None else prepared.get((sym, minutes))
            signal = first_reversal(intraday.get(sym), day, minutes, cached)
            if signal is None:
                continue
            outcome = lod_outcome(
                entry=signal["entry_price"],
                stop=signal["stop_price"],
                day_bars=intraday.get(sym),
                entry_end=signal["entry_end"],
                daily=daily.get(sym),
                entry_day=entry_day,
                forward_days=forward,
            )
            rows.append(
                {
                    "symbol": sym,
                    "timeframe": minutes,
                    "entry_time": signal["entry_time"],
                    "pattern": signal["pattern"],
                    "qualified": signal["qualified"],
                    "finished_2u": signal["finished_2u"],
                    **outcome,
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
                "timeframe": 0,
                "entry_time": clock,
                "pattern": None,
                "qualified": 0,
                "finished_2u": 0,
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


def _select(rows: Sequence[Mapping], minutes: int, qualified_only: bool, first_only: bool) -> list[Mapping]:
    chosen = [row for row in rows if int(row.get("timeframe") or 0) == minutes]
    if qualified_only:
        chosen = [row for row in chosen if int(row.get("qualified") or 0) == 1]
    if not first_only:
        return chosen
    by_day: dict[str, Mapping] = {}
    for row in chosen:
        day = str(row["date"])
        current = by_day.get(day)
        key = (str(row.get("entry_time")), str(row.get("symbol")))
        if current is None or key < (str(current.get("entry_time")), str(current.get("symbol"))):
            by_day[day] = row
    return list(by_day.values())


def _pattern_counts(rows: Sequence[Mapping]) -> dict[str, int]:
    counts = {pattern: 0 for pattern in PATTERNS}
    for row in rows:
        pattern = row.get("pattern")
        if pattern in counts:
            counts[pattern] += 1
    return counts


def _daily_avg_r(trades: Sequence[Mapping]) -> dict[str, dict[str, float]]:
    """Equal-weight stop-aware R of the book each morning, on mornings that have finished the horizon."""
    by_date: dict[str, list[Mapping]] = {}
    for trade in trades:
        by_date.setdefault(str(trade["date"]), []).append(trade)
    out = {name: {} for name, _, _ in HORIZONS}
    for day, rows in by_date.items():
        for name, _idx, _field in HORIZONS:
            if not _horizon_done(rows, name):
                continue
            values = []
            for row in rows:
                r_value = realized_lod_r(row, name)
                if r_value is not None:
                    values.append(r_value)
            if values:
                out[name][day] = sum(values) / len(values)
    return out


def build_reversal_stats(
    leader_rows: Sequence[Mapping],
    qqq_rows: Sequence[Mapping],
    rma_first_rows: Sequence[Mapping] = (),
) -> dict:
    """Eight books: 15- and 30-minute, each with and without the 20 RMA, all names and first name."""
    qqq = {(str(row["date"]), str(row["entry_time"])): row for row in qqq_rows}
    rma_daily = _daily_avg_r(rma_first_rows)
    books = {}
    for book_id, minutes, qualified_only, first_only, label, title in STRAT_BOOKS:
        rows = _select(leader_rows, minutes, qualified_only, first_only)
        body = _summarize_book(rows, qqq)
        daily = _daily_avg_r(rows)
        for name, _idx, _field in HORIZONS:
            both = [daily[name][day] - rma_daily[name][day] for day in daily[name] if day in rma_daily[name]]
            body["horizons"][name]["vs_rma_first"] = _mean(both)
        finished = [int(row.get("finished_2u") or 0) for row in rows]
        body["id"] = book_id
        body["label"] = label
        body["title"] = title
        body["timeframe"] = minutes
        body["pattern_counts"] = _pattern_counts(rows)
        body["finished_2u_rate"] = (sum(finished) / len(finished)) if finished else None
        books[book_id] = body

    ranked = []
    for index, (book_id, *_rest) in enumerate(STRAT_BOOKS):
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
        "order": [book_id for book_id, *_rest in STRAT_BOOKS],
        "panels": [
            {"title": "15-minute", "books": ["15_all", "15_first", "15_rma_all", "15_rma_first"]},
            {"title": "30-minute", "books": ["30_all", "30_first", "30_rma_all", "30_rma_first"]},
        ],
        "best": best,
        "benchmark": benchmark,
    }
