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


# The single-entry study is separate from the 1% check-in holds above.
# 1R there is the distance from the entry down to the low of day through the entry bar.
EMA_LENGTH = 20
EMA_EARLIEST = time(9, 45)
SINGLE_CLOCK = "10:30"
PCT_FIELD = {name: f"{name}_pct" if name != "eod" else "eod_pct" for name, _, _ in HORIZONS}
# (id, stored rule, first-name only, label)
SINGLE_BOOKS: tuple[tuple[str, str, bool, str], ...] = (
    ("rma_all", "rma1030", False, "10:30 all"),
    ("rma_first", "rma1030", True, "10:30 first"),
    ("ema_all", "ema", False, "EMA all"),
    ("ema_first", "ema", True, "EMA first"),
)


def ema(closes: Sequence[float], length: int = EMA_LENGTH) -> list[float]:
    """TradingView ``ta.ema``: SMA seed, then ``alpha * src + (1 - alpha) * prev``, ``alpha = 2 / (length + 1)``."""
    n = len(closes)
    out = [float("nan")] * n
    if n < length or length < 1:
        return out
    out[length - 1] = sum(closes[:length]) / length
    alpha = 2.0 / (length + 1)
    for i in range(length, n):
        out[i] = alpha * closes[i] + (1.0 - alpha) * out[i - 1]
    return out


def first_close_above_ema(
    bars: Optional[pd.DataFrame],
    day: str,
    length: int = EMA_LENGTH,
    earliest: time = EMA_EARLIEST,
) -> Optional[pd.Timestamp]:
    """First bar of ``day`` at or after 9:45 whose close is above the 20 EMA.

    Earlier sessions warm the average. A bar that ends before 9:45 cannot be the entry, even when
    its close is already above the average. Close must be strictly above.
    """
    if bars is None or bars.empty:
        return None
    start = pd.Timestamp(day)
    prior = bars.loc[bars.index < start]
    today = bars.loc[(bars.index >= start) & (bars.index < start + pd.Timedelta(days=1))]
    if today.empty:
        return None
    combined = pd.concat([prior, today]) if not prior.empty else today
    values = ema([float(value) for value in combined["close"]], length)
    offset = len(prior)
    for i, ts in enumerate(today.index):
        stamp = pd.Timestamp(ts)
        if stamp.time() < earliest:
            continue
        value = values[offset + i]
        if value == value and float(today.iloc[i].close) > value:
            return stamp
    return None


def to_pct(entry: float, price) -> Optional[float]:
    """Percent change from the entry. A close 3% above the entry is +3."""
    if price is None or pd.isna(price) or entry <= 0:
        return None
    return (float(price) / entry - 1.0) * 100.0


def lod_outcome(
    *,
    entry: float,
    stop: Optional[float],
    day_bars: Optional[pd.DataFrame],
    entry_end: Optional[pd.Timestamp],
    daily: Optional[pd.DataFrame],
    entry_day: pd.Timestamp,
    forward_days: Sequence[pd.Timestamp],
) -> dict:
    """Low-of-day stop. A touch exits at the stop; a gap through it exits at the open.

    ``stop`` is the session low from 9:30 through the entry bar. None means a hold with no stop
    (QQQ). The entry bar is not a fill. Later 5-minute bars cover the rest of the session and the
    next five sessions. A forward session with no 5-minute bars uses that day's daily bar. The
    stopping bar's high is not credited. Close-to-close percent is stored beside the exit.
    """
    use_stop = stop is not None and stop == stop and entry > 0 and stop < entry
    level = float(stop) if use_stop else None
    best_high = entry
    stopped = False
    stop_day: Optional[int] = None
    gapped = 0
    exit_price: Optional[float] = None

    def note_bar(high: float, low: float, open_: float, day_index: int) -> bool:
        nonlocal best_high, stopped, stop_day, gapped, exit_price
        if stopped:
            return True
        if level is not None and low <= level:
            stopped = True
            stop_day = day_index
            gapped = int(open_ < level)
            exit_price = open_ if gapped else level
            return True
        best_high = max(best_high, high)
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
    closes = {"eod_pct": to_pct(entry, eod_price)}
    for offset, (name, _idx, _field) in enumerate(HORIZONS[1:], start=1):
        bar = _daily_on(daily, forward_days[offset - 1]) if offset <= len(forward_days) else None
        closes[PCT_FIELD[name]] = None if bar is None else to_pct(entry, bar.close)
    stop_pct = ((entry - level) / entry * 100.0) if level is not None and entry > 0 else None
    return {
        "entry_price": entry,
        "stop_price": level,
        "stop_pct": stop_pct,
        **closes,
        "stopped": int(stopped),
        "stop_day": stop_day,
        "exit_pct": to_pct(entry, exit_price),
        "gapped": gapped,
        "mfe_pct": to_pct(entry, best_high),
    }


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


def _clock_minutes(hhmm: str) -> int:
    hour, minute = str(hhmm).split(":")
    return int(hour) * 60 + int(minute)


def format_clock(minutes: Optional[float]) -> Optional[str]:
    """Nearest minute, without a leading zero on the hour."""
    if minutes is None:
        return None
    total = int(round(minutes)) % (24 * 60)
    hour, minute = divmod(total, 60)
    return f"{hour}:{minute:02d}"


def realized_pct(row: Mapping, horizon: str) -> Optional[float]:
    """Stop-aware percent. From the stop day on this is the exit, at the stop or at the gap open."""
    idx = HORIZON_INDEX[horizon]
    stop_day = row.get("stop_day")
    if row.get("stopped") and stop_day is not None and int(stop_day) <= idx:
        ret = row.get("exit_pct")
        return None if ret is None else float(ret)
    ret = row.get(PCT_FIELD[horizon])
    return None if ret is None else float(ret)


def realized_lod_r(row: Mapping, horizon: str) -> Optional[float]:
    """Stop-aware R. 1R is the entry-to-stop distance. A gap can be worse than −1R."""
    pct = realized_pct(row, horizon)
    risk = row.get("stop_pct")
    if pct is None or risk is None or float(risk) <= 0:
        return None
    return pct / float(risk)


def _mfe_r(row: Mapping) -> Optional[float]:
    mfe = row.get("mfe_pct")
    risk = row.get("stop_pct")
    if mfe is None or risk is None or float(risk) <= 0:
        return None
    return float(mfe) / float(risk)


def _horizon_done(rows: Sequence[Mapping], horizon: str) -> bool:
    """A morning still in progress would otherwise contribute only the names that already stopped."""
    idx = HORIZON_INDEX[horizon]
    field = PCT_FIELD[horizon]
    return any(row.get(field) is not None for row in rows) or all(
        row.get("stopped") and row.get("stop_day") is not None and int(row["stop_day"]) <= idx for row in rows
    )


def _summarize_book(trades: Sequence[Mapping], qqq: Mapping[tuple, Mapping]) -> dict:
    """Day-equal average. Expectancy, win rate, and the distribution are per fill.

    QQQ is keyed by (date, entry clock). A morning's benchmark is the equal-weight QQQ hold from
    each fill's own entry minute.
    """
    by_date: dict[str, list[Mapping]] = {}
    for trade in trades:
        by_date.setdefault(str(trade["date"]), []).append(trade)
    entry_minutes = [_clock_minutes(str(trade["entry_time"])) for trade in trades if trade.get("entry_time")]
    risks = [float(trade["stop_pct"]) for trade in trades if trade.get("stop_pct") is not None and float(trade["stop_pct"]) > 0]
    horizons = {}
    for name, idx, _field in HORIZONS:
        daily_pct: list[float] = []
        daily_r: list[float] = []
        daily_excess: list[float] = []
        trade_pct: list[float] = []
        trade_r: list[float] = []
        mfes: list[float] = []
        resolved = 0
        stopped_n = 0
        gaps = 0
        for day, rows in by_date.items():
            if not _horizon_done(rows, name):
                continue
            morning_pct: list[float] = []
            morning_r: list[float] = []
            paired_pct: list[float] = []
            paired_qqq: list[float] = []
            for row in rows:
                pct = realized_pct(row, name)
                if pct is None:
                    continue
                resolved += 1
                morning_pct.append(pct)
                trade_pct.append(pct)
                r_value = realized_lod_r(row, name)
                if r_value is not None:
                    morning_r.append(r_value)
                    trade_r.append(r_value)
                mfe = _mfe_r(row)
                if mfe is not None:
                    mfes.append(mfe)
                stop_day = row.get("stop_day")
                if row.get("stopped") and stop_day is not None and int(stop_day) <= idx:
                    stopped_n += 1
                    if row.get("gapped"):
                        gaps += 1
                benchmark = qqq.get((day, str(row.get("entry_time"))))
                q_pct = realized_pct(benchmark, name) if benchmark else None
                if q_pct is not None:
                    paired_pct.append(pct)
                    paired_qqq.append(q_pct)
            if morning_pct:
                daily_pct.append(sum(morning_pct) / len(morning_pct))
            if morning_r:
                daily_r.append(sum(morning_r) / len(morning_r))
            if paired_pct:
                daily_excess.append(sum(paired_pct) / len(paired_pct) - sum(paired_qqq) / len(paired_qqq))
        horizons[name] = {
            "n_days": len(daily_pct),
            "n_trades": len(trade_pct),
            "avg_pct": _mean(daily_pct),
            "avg_r": _mean(daily_r),
            "win_rate": (sum(v > 0 for v in trade_pct) / len(trade_pct)) if trade_pct else None,
            "stop_hit_rate": (stopped_n / resolved) if resolved else None,
            "gap_count": gaps,
            "total_r": sum(trade_r) if trade_r else None,
            "expectancy": _mean(trade_r),
            "avg_mfe": _mean(mfes),
            "median_r": float(median(trade_r)) if trade_r else None,
            "best_r": max(trade_r) if trade_r else None,
            "worst_r": min(trade_r) if trade_r else None,
            "median_pct": float(median(trade_pct)) if trade_pct else None,
            "best_pct": max(trade_pct) if trade_pct else None,
            "worst_pct": min(trade_pct) if trade_pct else None,
            "vs_qqq": _mean(daily_excess),
        }
    return {
        "n_fills": len(trades),
        "avg_entry": format_clock(_mean(entry_minutes) if entry_minutes else None),
        "median_entry": format_clock(float(median(entry_minutes))) if entry_minutes else None,
        "avg_stop_pct": _mean(risks),
        "horizons": horizons,
    }


def build_single_stats(leader_rows: Sequence[Mapping], qqq_rows: Sequence[Mapping]) -> dict:
    """Four books: 10:30 RMA and first-EMA-close, each as all names and as the first name only."""
    qqq = {(str(row["date"]), str(row["entry_time"])): row for row in qqq_rows}
    books = {}
    for book_id, rule, first_only, label in SINGLE_BOOKS:
        rows = [row for row in leader_rows if row.get("rule") == rule]
        if first_only:
            rows = [row for row in rows if int(row.get("rank") or 0) == 1]
        body = _summarize_book(rows, qqq)
        body["id"] = book_id
        body["label"] = label
        body["rule"] = rule
        books[book_id] = body
    return {"books": books, "order": [book_id for book_id, *_rest in SINGLE_BOOKS]}


def single_entry_text() -> str:
    return (
        "Two entry rules, each with every qualifying name and with only the first name that day. "
        "The 10:30 book buys a top-10 leader at the 10:30 close once a 5-minute bar has closed above "
        "the 20 RMA. The EMA book buys at the close of the first 5-minute bar at or after 9:45 that "
        "closes above the 20-period EMA; earlier sessions warm that average, and nothing before 9:45 "
        "is an entry. The stop is the low from 9:30 through the entry bar. One R is that distance. "
        "A later bar at or below the stop exits at the stop. A bar that opens below the stop exits at "
        "the open and is counted as a gap. Ties break by symbol."
    )


def single_entries_for_day(
    day: str,
    symbols: Sequence[str],
    intraday: Mapping[str, pd.DataFrame],
    daily: Mapping[str, pd.DataFrame],
    calendar: Sequence[str],
) -> tuple[list[dict], list[dict]]:
    """Low-of-day outcomes for the 10:30 RMA book and the EMA book, plus QQQ at each entry clock."""
    forward = [pd.Timestamp(d) for d in calendar if d > day][:5]
    entry_day = pd.Timestamp(day)
    end_1030 = window_end(day, SINGLE_CLOCK)
    leaders: list[dict] = []

    rma_rows = []
    for sym in symbols:
        bars = intraday.get(sym)
        cross = cross_through(bars, end_1030)
        entry = entry_at(bars, end_1030)
        stop = session_low_through(bars, end_1030)
        if cross is None or entry is None or stop is None or stop >= entry:
            continue
        rma_rows.append(
            {
                "symbol": sym,
                "cross": cross,
                "entry_time": SINGLE_CLOCK,
                "bars": bars,
                "entry": entry,
                "stop": stop,
            }
        )
    rma_rows.sort(key=lambda row: (row["cross"], row["symbol"]))
    for rank, row in enumerate(rma_rows, start=1):
        leaders.append(
            {
                "symbol": row["symbol"],
                "rule": "rma1030",
                "entry_time": row["entry_time"],
                "rank": rank,
                "cross_time": pd.Timestamp(row["cross"]).strftime("%H:%M"),
                **lod_outcome(
                    entry=row["entry"],
                    stop=row["stop"],
                    day_bars=row["bars"],
                    entry_end=end_1030,
                    daily=daily.get(row["symbol"]),
                    entry_day=entry_day,
                    forward_days=forward,
                ),
            }
        )

    ema_rows = []
    for sym in symbols:
        bars = intraday.get(sym)
        cross = first_close_above_ema(bars, day)
        if cross is None:
            continue
        entry = entry_at(bars, cross)
        stop = session_low_through(bars, cross)
        if entry is None or stop is None or stop >= entry:
            continue
        ema_rows.append({"symbol": sym, "cross": cross, "bars": bars, "entry": entry, "stop": stop})
    ema_rows.sort(key=lambda row: (row["cross"], row["symbol"]))
    for rank, row in enumerate(ema_rows, start=1):
        leaders.append(
            {
                "symbol": row["symbol"],
                "rule": "ema",
                "entry_time": pd.Timestamp(row["cross"]).strftime("%H:%M"),
                "rank": rank,
                "cross_time": pd.Timestamp(row["cross"]).strftime("%H:%M"),
                **lod_outcome(
                    entry=row["entry"],
                    stop=row["stop"],
                    day_bars=row["bars"],
                    entry_end=pd.Timestamp(row["cross"]),
                    daily=daily.get(row["symbol"]),
                    entry_day=entry_day,
                    forward_days=forward,
                ),
            }
        )

    clocks = {row["entry_time"] for row in leaders}
    clocks.add(SINGLE_CLOCK)
    qqq_bars = intraday.get(BENCHMARK)
    qqq_rows = []
    for clock in sorted(clocks):
        end = window_end(day, clock)
        price = entry_at(qqq_bars, end)
        if price is None:
            continue
        qqq_rows.append(
            {
                "symbol": BENCHMARK,
                "rule": "qqq",
                "entry_time": clock,
                "rank": None,
                "cross_time": None,
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
    return leaders, qqq_rows
