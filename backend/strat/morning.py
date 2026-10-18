"""Morning check-in times. Buy a day's leaders only after the 5-minute chart closes above its 20 RMA.

No lookahead. A check-in at 10:15 uses 5-minute bars that have *ended* by 10:15. The rest of the
day is an outcome, not an input. The 20-period RMA (Wilder, TradingView ``ta.rma``) is warmed up on
earlier sessions so it already has a value at the open. A prior session's close above that average
does not count: the cross is the first bar of *this* session.

A name that has not closed above the RMA by the check-in is not bought. Among the names that have,
the earliest cross is first. Ties break by symbol. The entry is the close of the 5-minute bar that
ends at the check-in, not the close of the cross bar. The earliest buy is 9:45.

The stop is the low of day so far: the lowest low from the 9:30 bar through that entry bar. The
entry bar is not itself a stop; that low is already in the level. A later bar stops the trade when
it trades below that low. Later same-day bars are walked in order. A bar that trades below the stop
fills at the stop and does not donate its high (the order inside one bar is unknown). Later sessions
use the daily low the same way. Close-to-close returns are stored beside the stopped return.
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

# The question the summary answers: which clock time has the best close-to-close return by this session.
# The low-of-day stop is reported beside it (hit rate and stop-aware expectancy). It is not the ranking.
PRIMARY_HORIZON = "d3"

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


def _pct(entry: float, price) -> Optional[float]:
    if price is None or pd.isna(price) or entry <= 0:
        return None
    return (float(price) / entry - 1.0) * 100.0


def _daily_on(daily: Optional[pd.DataFrame], day: pd.Timestamp) -> Optional[pd.Series]:
    if daily is None or daily.empty:
        return None
    stamp = pd.Timestamp(day).normalize()
    if stamp in daily.index:
        return daily.loc[stamp]
    return None


def outcome_for_entry(
    *,
    entry: float,
    stop: Optional[float],
    day_bars: Optional[pd.DataFrame],
    entry_end: Optional[pd.Timestamp],
    daily: Optional[pd.DataFrame],
    entry_day: pd.Timestamp,
    forward_days: Sequence[pd.Timestamp],
) -> dict:
    """Close returns, the low-of-day stop, and the excursion of the path actually traded.

    ``stop`` is the session low from 9:30 through the entry candle, or None for QQQ (a hold, not a
    stopped trade). A later bar stops the trade only when its low is below that level. The entry
    candle is already inside the level, so it is not a fill.
    """
    best_high = entry
    worst_low = entry
    stopped = False
    stop_day: Optional[int] = None

    def note_bar(high: float, low: float, day_index: int) -> bool:
        """Record the bar. True when it stops the trade (and its high is ignored)."""
        nonlocal best_high, worst_low, stopped, stop_day
        if stopped:
            return True
        if stop is not None and low < stop:
            stopped = True
            stop_day = day_index
            worst_low = min(worst_low, stop)
            return True
        best_high = max(best_high, high)
        worst_low = min(worst_low, low)
        return False

    bars = day_bars if day_bars is not None else pd.DataFrame()
    path = bars.loc[bars.index > entry_end] if entry_end is not None and not bars.empty else bars.iloc[0:0]
    for row in path.itertuples():
        if note_bar(float(row.high), float(row.low), 0):
            break

    if not stopped:
        for offset, day in enumerate(forward_days[:5], start=1):
            bar = _daily_on(daily, day)
            if bar is None:
                continue
            if note_bar(float(bar.high), float(bar.low), offset):
                break

    today = _daily_on(daily, entry_day)
    eod_price = None if today is None else today.close
    if eod_price is None and not bars.empty:
        eod_price = float(bars.iloc[-1].close)
    closes = {"eod_ret": _pct(entry, eod_price)}
    for offset, (_name, _idx, field) in enumerate(HORIZONS[1:], start=1):
        bar = _daily_on(daily, forward_days[offset - 1]) if offset <= len(forward_days) else None
        closes[field] = None if bar is None else _pct(entry, bar.close)

    stop_ret = _pct(entry, stop) if stopped and stop is not None else None
    return {
        "entry_price": entry,
        "candle_low": stop,
        **closes,
        "stopped": int(stopped),
        "stop_day": stop_day,
        "stop_ret": stop_ret,
        "mfe": _pct(entry, best_high),
        "mae": _pct(entry, worst_low),
    }


def realized_return(row: Mapping, horizon: str) -> Optional[float]:
    """Stop-aware return through ``horizon``. The stop replaces the close once it has been hit."""
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


def _raw_return(row: Mapping, horizon: str) -> Optional[float]:
    ret = row.get(HORIZON_FIELD[horizon])
    return None if ret is None else float(ret)


def summarize_window(trades: Sequence[Mapping]) -> dict:
    """Day-equal stats. Each morning weighs the same, however many of the ten filled.

    Average, median and win rate use the close-to-close return (the hold). Expectancy uses the
    stop: the low-of-day fill once a later bar has traded below it, otherwise the same close.
    The stop-hit rate is trade-level, over fills whose path through that horizon is known.
    """
    by_date: dict[str, list[Mapping]] = {}
    for trade in trades:
        by_date.setdefault(str(trade["date"]), []).append(trade)
    horizons = {}
    for name, idx, _field in HORIZONS:
        raw_daily: list[float] = []
        stopped_daily: list[float] = []
        raw_trades = 0
        resolved_trades = 0
        stopped_trades = 0
        for rows in by_date.values():
            raws = [r for row in rows if (r := _raw_return(row, name)) is not None]
            reals = [r for row in rows if (r := realized_return(row, name)) is not None]
            if raws:
                raw_daily.append(sum(raws) / len(raws))
                raw_trades += len(raws)
            if reals:
                stopped_daily.append(sum(reals) / len(reals))
            for row in rows:
                if _resolved(row, name):
                    resolved_trades += 1
                    stop_day = row.get("stop_day")
                    if row.get("stopped") and stop_day is not None and int(stop_day) <= idx:
                        stopped_trades += 1
        horizons[name] = {
            "n_days": len(raw_daily),
            "n_trades": raw_trades,
            "avg": _mean(raw_daily),
            "median": float(median(raw_daily)) if raw_daily else None,
            "win_rate": (sum(v > 0 for v in raw_daily) / len(raw_daily)) if raw_daily else None,
            "expectancy": _mean(stopped_daily),
            "stop_hit_rate": (stopped_trades / resolved_trades) if resolved_trades else None,
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
    """Equal-weight close-to-close return of the basket each morning. The benchmarks use this hold."""
    grouped: dict[str, list[float]] = {}
    for trade in trades:
        ret = _raw_return(trade, horizon)
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
    """Highest average close-to-close return at the primary horizon, then win rate."""
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
        "vs_qqq": windows[window]["vs_qqq"].get(horizon),
        "avg_qualified": windows[window].get("avg_qualified"),
    }


def definition_text() -> str:
    return (
        "A name is bought at a check-in only after a 5-minute bar has closed above its 20-period RMA "
        "(Wilder smoothing, the same average as TradingView ta.rma). Earlier sessions warm that average "
        "so it is valid at the open; they do not count as the cross. The earliest cross is bought first. "
        "The entry is the close of the 5-minute bar that ends at the check-in. "
        "The stop is the low of the session from 9:30 through that bar."
    )


def iter_windows() -> Iterable[str]:
    return WINDOW_IDS
