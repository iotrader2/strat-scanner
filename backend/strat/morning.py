"""Morning check-in times. Buy a day's leaders only after the 5-minute chart closes above its 20 RMA.

No lookahead. A check-in at 10:15 uses 5-minute bars that have *ended* by 10:15. The rest of the
day is an outcome, not an input. The 20-period RMA (Wilder, TradingView ``ta.rma``) is warmed up on
earlier sessions so it already has a value at the open. A prior session's close above that average
does not count: the cross is the first bar of *this* session.

A name that has not closed above the RMA by the check-in is not bought. Among the names that have,
the earliest cross is first. Ties break by symbol. The entry is the close of the 5-minute bar that
ends at the check-in, not the close of the cross bar. The earliest buy is 9:45.

The stop is 1% under the entry (1R, since 1R is 1% of the entry). The entry bar is not a stop.
A later 5-minute bar, through the rest of the session and the next five sessions, stops the trade
when it trades at or below that level. The booked result from the stop day on is −1R. A bar that
opens below the stop is a gap: it still books −1R, and the gap is counted. That bar's high is not
credited, because the order inside one bar is unknown.
"""

from __future__ import annotations

from datetime import time
from statistics import median
from typing import Iterable, Mapping, Optional, Sequence

import pandas as pd

# (label, bar end in America/New_York). The bar that ends at 09:45 opened at 09:30.
WINDOWS: tuple[tuple[str, time], ...] = (
    ("09:45", time(9, 45)),
    ("10:00", time(10, 0)),
    ("10:15", time(10, 15)),
    ("10:30", time(10, 30)),
    ("10:45", time(10, 45)),
)
WINDOW_IDS: tuple[str, ...] = tuple(label for label, _ in WINDOWS)
BENCHMARK = "QQQ"
TOP_N = 10

# Which clock has the best stop-aware result by this session. 1R is 1% of the entry.
PRIMARY_HORIZON = "d3"
# 1R is this many percent of the entry. The stop is one R under the fill, so a stopped trade is −1R.
R_PERCENT = 1.0
STOP_R = 1.0

HORIZONS: tuple[tuple[str, int, str], ...] = (
    ("eod", 0, "eod_ret"),
    ("d1", 1, "d1_ret"),
    ("d2", 2, "d2_ret"),
    ("d3", 3, "d3_ret"),
    ("d4", 4, "d4_ret"),
    ("d5", 5, "d5_ret"),
)
HORIZON_INDEX = {name: idx for name, idx, _ in HORIZONS}
HORIZON_FIELD = {name: field for name, _, field in HORIZONS}

# TradingView ta.rma length. The first value is the SMA of this many closes; after that Wilder.
RMA_LENGTH = 20


def window_end(day: str, label: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {label}")


def bars_through(day_bars: Optional[pd.DataFrame], end: pd.Timestamp) -> pd.DataFrame:
    """Bars whose end is at or before ``end``. Later bars are invisible."""
    if day_bars is None or day_bars.empty:
        return pd.DataFrame()
    return day_bars.loc[day_bars.index <= end]


def wilder_rma(closes: Sequence[float], length: int = RMA_LENGTH) -> list[float]:
    """TradingView ``ta.rma``: SMA seed, then ``(src + (length - 1) * prev) / length``.

    Values before the seed are NaN. A series shorter than ``length`` is all NaN.
    """
    n = len(closes)
    out = [float("nan")] * n
    if n < length or length < 1:
        return out
    out[length - 1] = sum(closes[:length]) / length
    for i in range(length, n):
        out[i] = (closes[i] + (length - 1) * out[i - 1]) / length
    return out


def _split_session(bars: pd.DataFrame, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prior bars, then today's bars that have closed by ``end``. Later bars are dropped."""
    day = pd.Timestamp(end).normalize()
    prior = bars.loc[bars.index < day]
    today = bars.loc[(bars.index >= day) & (bars.index <= end)]
    return prior, today


def cross_through(bars: Optional[pd.DataFrame], end: pd.Timestamp, length: int = RMA_LENGTH) -> Optional[pd.Timestamp]:
    """End time of the first *today* bar, at or before ``end``, whose close is above the RMA.

    ``bars`` may include earlier sessions; those warm the average and cannot themselves be the cross.
    None when the average is not warmed up yet, or no bar has closed above it.
    """
    if bars is None or bars.empty:
        return None
    prior, today = _split_session(bars, end)
    if today.empty:
        return None
    combined = pd.concat([prior, today]) if not prior.empty else today
    rma = wilder_rma([float(value) for value in combined["close"]], length)
    offset = len(prior)
    for i, ts in enumerate(today.index):
        value = rma[offset + i]
        if value == value and float(today.iloc[i].close) > value:
            return pd.Timestamp(ts)
    return None


def entry_at(bars: Optional[pd.DataFrame], end: pd.Timestamp) -> Optional[float]:
    """Close of the bar that ends exactly at the check-in. Missing bar means no fill."""
    if bars is None or bars.empty or end not in bars.index:
        return None
    price = float(bars.loc[end].close)
    return price if price > 0 and price == price else None


def session_low_through(bars: Optional[pd.DataFrame], end: pd.Timestamp) -> Optional[float]:
    """Lowest low from the 9:30 bar through ``end``. Prior sessions are not the low of today."""
    if bars is None or bars.empty:
        return None
    _prior, today = _split_session(bars, end)
    if today.empty:
        return None
    low = float(today["low"].min())
    return low if low == low else None


def to_r(entry: float, price) -> Optional[float]:
    """Distance from the entry in R. A close 3% above the entry is +3R."""
    if price is None or pd.isna(price) or entry <= 0:
        return None
    return (float(price) / entry - 1.0) * (100.0 / R_PERCENT)


def fixed_stop(entry: float) -> float:
    """Price one R under the entry."""
    return entry * (1.0 - STOP_R * R_PERCENT / 100.0)


def _at_stop(entry: float, price: float) -> bool:
    """Traded at or below the stop. Measured in R so entry × 0.99 counts."""
    return to_r(entry, price) <= -STOP_R


def _opened_through(entry: float, price: float) -> bool:
    """Opened strictly below the stop, so the trade could not fill at the stop price."""
    value = to_r(entry, price)
    return value is not None and value < -STOP_R


def _daily_on(daily: Optional[pd.DataFrame], day: pd.Timestamp) -> Optional[pd.Series]:
    if daily is None or daily.empty:
        return None
    stamp = pd.Timestamp(day).normalize()
    if stamp in daily.index:
        return daily.loc[stamp]
    return None


def _bars_on(bars: pd.DataFrame, day: pd.Timestamp, after: Optional[pd.Timestamp]) -> pd.DataFrame:
    """One session of 5-minute bars. ``after`` drops the entry bar and everything before it."""
    if bars is None or bars.empty:
        return pd.DataFrame()
    start = pd.Timestamp(day).normalize()
    chunk = bars.loc[(bars.index >= start) & (bars.index < start + pd.Timedelta(days=1))]
    if after is not None and not chunk.empty:
        chunk = chunk.loc[chunk.index > after]
    return chunk


def outcome_for_entry(
    *,
    entry: float,
    with_stop: bool,
    day_bars: Optional[pd.DataFrame],
    entry_end: Optional[pd.Timestamp],
    daily: Optional[pd.DataFrame],
    entry_day: pd.Timestamp,
    forward_days: Sequence[pd.Timestamp],
) -> dict:
    """Close results in R, the 1% stop, and the excursion of the path actually traded.

    ``with_stop`` is false for QQQ, which is a hold. A later 5-minute bar stops the trade when its
    low is at or below entry × 0.99. The rest of the entry day comes first, then the next five
    sessions. A session with no 5-minute bars uses that day's daily bar. The entry bar is not a
    fill. From the stop day on the booked result is −1R, including when the bar opens through the
    stop. The stopping bar's high is ignored. Close-to-close R is stored beside that.
    """
    level = fixed_stop(entry) if with_stop else None
    best_high = entry
    worst_low = entry
    stopped = False
    stop_day: Optional[int] = None
    gapped = 0

    def note_bar(high: float, low: float, open_: float, day_index: int) -> bool:
        """Record the bar. True when it stops the trade."""
        nonlocal best_high, worst_low, stopped, stop_day, gapped
        if stopped:
            return True
        if level is not None and _at_stop(entry, low):
            stopped = True
            stop_day = day_index
            gapped = int(_opened_through(entry, open_))
            worst_low = min(worst_low, low)
            return True
        best_high = max(best_high, high)
        worst_low = min(worst_low, low)
        return False

    bars = day_bars if day_bars is not None else pd.DataFrame()
    sessions: list[tuple[int, pd.Timestamp, Optional[pd.Timestamp]]] = [
        (0, pd.Timestamp(entry_day).normalize(), entry_end)
    ]
    for offset, day in enumerate(forward_days[:5], start=1):
        sessions.append((offset, pd.Timestamp(day).normalize(), None))
    for offset, day, after in sessions:
        chunk = _bars_on(bars, day, after)
        if not chunk.empty:
            for row in chunk.itertuples():
                if note_bar(float(row.high), float(row.low), float(row.open), offset):
                    break
        elif offset > 0:
            bar = _daily_on(daily, day)
            if bar is not None:
                note_bar(float(bar.high), float(bar.low), float(bar.open), offset)
        if stopped:
            break

    today = _daily_on(daily, entry_day)
    eod_price = None if today is None else today.close
    if eod_price is None and not bars.empty:
        same_day = _bars_on(bars, pd.Timestamp(entry_day), None)
        if not same_day.empty:
            eod_price = float(same_day.iloc[-1].close)
    closes = {"eod_ret": to_r(entry, eod_price)}
    for offset, (_name, _idx, field) in enumerate(HORIZONS[1:], start=1):
        bar = _daily_on(daily, forward_days[offset - 1]) if offset <= len(forward_days) else None
        closes[field] = None if bar is None else to_r(entry, bar.close)

    return {
        "entry_price": entry,
        "candle_low": level,
        **closes,
        "stopped": int(stopped),
        "stop_day": stop_day,
        "stop_ret": -STOP_R if stopped else None,
        "gapped": gapped,
        "mfe": to_r(entry, best_high),
        "mae": to_r(entry, worst_low),
    }


def realized_return(row: Mapping, horizon: str) -> Optional[float]:
    """Stop-aware R through ``horizon``. From the stop day on the result is −1R."""
    idx = HORIZON_INDEX[horizon]
    field = HORIZON_FIELD[horizon]
    stop_day = row.get("stop_day")
    if row.get("stopped") and stop_day is not None and int(stop_day) <= idx:
        ret = row.get("stop_ret")
        return None if ret is None else float(ret)
    ret = row.get(field)
    return None if ret is None else float(ret)


def _resolved(row: Mapping, horizon: str) -> bool:
    idx = HORIZON_INDEX[horizon]
    stop_day = row.get("stop_day")
    if row.get("stopped") and stop_day is not None and int(stop_day) <= idx:
        return row.get("stop_ret") is not None
    return row.get(HORIZON_FIELD[horizon]) is not None


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def summarize_window(trades: Sequence[Mapping]) -> dict:
    """Stop-aware R. Average gives each morning one vote. Expectancy is the mean R per fill.

    A stopped trade counts as −1R from the stop day on. Win rate and the stop-hit rate are
    trade-level, over fills whose path through that horizon is known. Total R is the sum of those
    fills. MFE is the best R reached before the stop or the end of the hold.
    """
    by_date: dict[str, list[Mapping]] = {}
    for trade in trades:
        by_date.setdefault(str(trade["date"]), []).append(trade)
    horizons = {}
    for name, idx, _field in HORIZONS:
        daily_avgs: list[float] = []
        trade_rs: list[float] = []
        mfes: list[float] = []
        resolved_trades = 0
        stopped_trades = 0
        gaps = 0
        field = HORIZON_FIELD[name]
        for rows in by_date.values():
            # A morning still in progress would otherwise contribute only the names that already stopped.
            finished = any(row.get(field) is not None for row in rows) or all(
                row.get("stopped") and row.get("stop_day") is not None and int(row["stop_day"]) <= idx for row in rows
            )
            if not finished:
                continue
            morning: list[float] = []
            for row in rows:
                if not _resolved(row, name):
                    continue
                ret = realized_return(row, name)
                if ret is None:
                    continue
                morning.append(ret)
                resolved_trades += 1
                stop_day = row.get("stop_day")
                if row.get("stopped") and stop_day is not None and int(stop_day) <= idx:
                    stopped_trades += 1
                    if row.get("gapped"):
                        gaps += 1
                mfe = row.get("mfe")
                if mfe is not None:
                    mfes.append(float(mfe))
            if morning:
                daily_avgs.append(sum(morning) / len(morning))
                trade_rs.extend(morning)
        horizons[name] = {
            "n_days": len(daily_avgs),
            "n_trades": len(trade_rs),
            "avg": _mean(daily_avgs),
            "median": float(median(daily_avgs)) if daily_avgs else None,
            "win_rate": (sum(v > 0 for v in trade_rs) / len(trade_rs)) if trade_rs else None,
            "expectancy": _mean(trade_rs),
            "total_r": sum(trade_rs) if trade_rs else None,
            "stop_hit_rate": (stopped_trades / resolved_trades) if resolved_trades else None,
            "gap_count": gaps,
            "avg_mfe": _mean(mfes),
        }
    days = {name: horizons[name]["n_days"] for name in horizons}
    return {
        "n_days": max(days.values()) if days else 0,
        "n_trades": max((horizons[name]["n_trades"] for name in horizons), default=0),
        "horizons": horizons,
    }


def _excess(strategy: Mapping, other: Mapping, horizon: str) -> Optional[float]:
    """Mean of (strategy day − other day) on mornings both sides have a number for."""
    return _paired_excess(strategy.get("_daily", {}).get(horizon, {}), other.get("_daily", {}).get(horizon, {}))


def _paired_excess(left: Mapping[str, float], right: Mapping[str, float]) -> Optional[float]:
    both = [left[day] - right[day] for day in left if day in right]
    return _mean(both)


def _daily_basket(trades: Sequence[Mapping], horizon: str) -> dict[str, float]:
    """Equal-weight stop-aware R of the basket each morning. QQQ has no stop, so this is its close."""
    grouped: dict[str, list[float]] = {}
    for trade in trades:
        ret = realized_return(trade, horizon)
        if ret is None:
            continue
        grouped.setdefault(str(trade["date"]), []).append(ret)
    return {day: sum(values) / len(values) for day, values in grouped.items()}


def qualification_by_window(rank_rows: Sequence[Mapping]) -> dict[str, dict]:
    """Names bought per morning, including mornings when nobody had crossed yet."""
    grouped: dict[str, dict[str, int]] = {w: {} for w in WINDOW_IDS}
    for row in rank_rows:
        window = row.get("window")
        if window not in grouped:
            continue
        day = str(row["date"])
        grouped[window].setdefault(day, 0)
        if row.get("qualified"):
            grouped[window][day] += 1
    out = {}
    for window, days in grouped.items():
        counts = list(days.values())
        out[window] = {
            "n_days": len(counts),
            "avg": (sum(counts) / len(counts)) if counts else None,
        }
    return out


def build_stats(
    leader_rows: Sequence[Mapping],
    qqq_rows: Sequence[Mapping],
    rank_rows: Sequence[Mapping] = (),
) -> dict:
    """Per-interval aggregates, QQQ at the same clock, and the best check-in on ``PRIMARY_HORIZON``."""
    qualified = qualification_by_window(rank_rows)
    leaders: dict[str, list[Mapping]] = {w: [] for w in WINDOW_IDS}
    for row in leader_rows:
        window = row.get("window")
        if window in leaders:
            leaders[window].append(row)
    qqq: dict[str, list[Mapping]] = {w: [] for w in WINDOW_IDS}
    for row in qqq_rows:
        window = row.get("window")
        if window in qqq:
            qqq[window].append(row)

    def pack(rows: Sequence[Mapping]) -> dict:
        stats = summarize_window(rows)
        stats["_daily"] = {name: _daily_basket(rows, name) for name, _, _ in HORIZONS}
        return stats

    packed = {window: pack(rows) for window, rows in leaders.items()}
    qqq_packed = {window: pack(rows) for window, rows in qqq.items()}
    windows = {}
    for window in WINDOW_IDS:
        body = {k: v for k, v in packed[window].items() if k != "_daily"}
        body["vs_qqq"] = {
            name: _paired_excess(packed[window]["_daily"][name], qqq_packed[window]["_daily"][name])
            for name, _, _ in HORIZONS
        }
        body["avg_qualified"] = qualified[window]["avg"]
        body["qualified_days"] = qualified[window]["n_days"]
        windows[window] = body

    best = _best_window(windows)
    qqq_body = {k: v for k, v in qqq_packed.get(best["window"] if best else "10:00", qqq_packed["10:00"]).items() if k != "_daily"}
    # QQQ displayed next to the intervals is the same-clock hold. Keep every window so the table can show one column.
    qqq_public = {}
    for window in WINDOW_IDS:
        qqq_public[window] = {k: v for k, v in qqq_packed[window].items() if k != "_daily"}
    return {
        "windows": windows,
        "qqq": qqq_public,
        "best": best,
        "primary_horizon": PRIMARY_HORIZON,
        "qqq_at_best": qqq_body,
    }


def _best_window(windows: Mapping[str, Mapping]) -> Optional[dict]:
    """Highest average stop-aware R at the primary horizon, then win rate."""
    horizon = PRIMARY_HORIZON

    def rank_at(name: str) -> list[tuple]:
        found = []
        for window in WINDOW_IDS:
            block = windows[window]["horizons"][name]
            if not block["n_days"] or block["avg"] is None:
                continue
            found.append((block["avg"], block["win_rate"] or 0.0, -WINDOW_IDS.index(window), window, block))
        return found

    ranked = rank_at(horizon) or rank_at("eod")
    if not ranked:
        return None
    if not rank_at(horizon):
        horizon = "eod"
    ranked.sort(reverse=True)
    _avg, _win, _order, window, block = ranked[0]
    return {
        "window": window,
        "horizon": horizon,
        "expectancy": block["expectancy"],
        "win_rate": block["win_rate"],
        "avg": block["avg"],
        "median": block["median"],
        "stop_hit_rate": block["stop_hit_rate"],
        "n_days": block["n_days"],
        "n_trades": block["n_trades"],
        "total_r": block.get("total_r"),
        "avg_mfe": block.get("avg_mfe"),
        "gap_count": block.get("gap_count"),
        "vs_qqq": windows[window]["vs_qqq"].get(horizon),
        "avg_qualified": windows[window].get("avg_qualified"),
    }


def definition_text() -> str:
    return (
        "A name is bought at a check-in only after a 5-minute bar has closed above its 20-period RMA "
        "(Wilder smoothing, the same average as TradingView ta.rma). Earlier sessions warm that average "
        "so it is valid at the open; they do not count as the cross. The earliest cross is bought first. "
        "The entry is the close of the 5-minute bar that ends at the check-in. "
        "The stop is 1% under that price. One R is 1% of the entry, so a stopped trade is −1R "
        "from the stop day on, including when a later 5-minute bar opens through the stop."
    )


def iter_windows() -> Iterable[str]:
    return WINDOW_IDS
