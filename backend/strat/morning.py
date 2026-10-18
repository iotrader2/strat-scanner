"""Morning check-in times. Rank a day's leaders from information known at that minute, then score the trade.

No lookahead. A check-in at 10:15 uses the session open and the 15-minute bars that have
*ended* by 10:15, plus QQQ over that same span. The rest of the day is an outcome, not an input.

"Best at that interval" (tunable; see ``IntervalWeights``)::

    score = move_weight * day_move
          + qqq_weight  * vs_qqq
          + or_weight   * opening_range_score

* ``day_move`` is the percent change from the session open (open of the 09:30–09:45 bar) to this candle's close.
* ``vs_qqq`` is that move minus QQQ's move over the same minutes. Missing QQQ contributes nothing.
* ``opening_range_score`` is where the close sits in the high–low of every bar from the open through this
  candle: +1 at the high, 0 in the middle, −1 at the low.

Defaults are 1, 1 and 1, so one percent of outperformance counts the same as closing at the high of the
range built so far. Override with ``STRAT_MORNING_W_MOVE``, ``STRAT_MORNING_W_QQQ`` and
``STRAT_MORNING_W_OR``, or pass a weights object. Ranks break ties by symbol so they are stable.

Outcomes assume a fill at the candle close and a stop at that candle's low. The entry candle itself is
not a stop: its low printed before the close. Later same-day bars are walked in order. A bar that trades
through the stop fills at the stop and does not donate its high (the order inside one bar is unknown).
Later sessions use the daily low the same way. Close-to-close returns are stored beside the stopped
return; they are not replaced by it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
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
OPEN_WINDOW = "open"
BENCHMARK = "QQQ"
TOP_N = 10

# The question the summary answers: which clock time has the best close-to-close return by this session.
# The candle-low stop is reported beside it (hit rate and stop-aware expectancy). It is not the ranking,
# because that low is one 15-minute wick and gets hit too often to separate the five times.
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


@dataclass(frozen=True)
class IntervalWeights:
    """Points added to the check-in score. See the module docstring for what each one multiplies."""

    move: float = 1.0
    vs_qqq: float = 1.0
    opening_range: float = 1.0


def weights_from_env() -> IntervalWeights:
    def pick(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None or not str(raw).strip():
            return default
        return float(raw)

    return IntervalWeights(
        move=pick("STRAT_MORNING_W_MOVE", 1.0),
        vs_qqq=pick("STRAT_MORNING_W_QQQ", 1.0),
        opening_range=pick("STRAT_MORNING_W_OR", 1.0),
    )


def window_end(day: str, label: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {label}")


def bars_through(day_bars: Optional[pd.DataFrame], end: pd.Timestamp) -> pd.DataFrame:
    """Bars whose end is at or before ``end``. Later bars are invisible."""
    if day_bars is None or day_bars.empty:
        return pd.DataFrame()
    return day_bars.loc[day_bars.index <= end]


def interval_features(
    day_bars: Optional[pd.DataFrame],
    qqq_bars: Optional[pd.DataFrame],
    end: pd.Timestamp,
) -> Optional[dict]:
    """Move, QQQ excess and opening-range position at one check-in. None when that candle is missing."""
    have = bars_through(day_bars, end)
    if have.empty or end not in have.index:
        return None
    opened = float(have.iloc[0].open)
    close = float(have.loc[end].close)
    if not opened or opened <= 0 or pd.isna(close):
        return None
    day_move = (close / opened - 1.0) * 100.0
    vs_qqq = None
    q_have = bars_through(qqq_bars, end)
    if not q_have.empty and end in q_have.index:
        q_open = float(q_have.iloc[0].open)
        q_close = float(q_have.loc[end].close)
        if q_open and q_open > 0 and not pd.isna(q_close):
            vs_qqq = day_move - (q_close / q_open - 1.0) * 100.0
    high = float(have.high.max())
    low = float(have.low.min())
    or_position = 0.5 if high <= low else (close - low) / (high - low)
    return {
        "day_move": day_move,
        "vs_qqq": vs_qqq,
        "or_position": or_position,
        "entry_price": close,
        "candle_low": float(have.loc[end].low),
        "candle_high": float(have.loc[end].high),
    }


def interval_score(features: Mapping, weights: Optional[IntervalWeights] = None) -> float:
    weights = weights or IntervalWeights()
    vs = 0.0 if features.get("vs_qqq") is None else float(features["vs_qqq"])
    or_score = (float(features["or_position"]) - 0.5) * 2.0
    return weights.move * float(features["day_move"]) + weights.vs_qqq * vs + weights.opening_range * or_score


def rank_at_window(
    features_by_symbol: Mapping[str, Optional[dict]],
    weights: Optional[IntervalWeights] = None,
) -> list[dict]:
    """Best first. Symbols with no candle at this check-in are left out, not ranked last on a guess."""
    weights = weights or IntervalWeights()
    ranked = []
    for symbol, features in features_by_symbol.items():
        if not features:
            continue
        ranked.append({"symbol": symbol, **features, "score": interval_score(features, weights)})
    ranked.sort(key=lambda row: (-row["score"], row["symbol"]))
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
    return ranked


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
    """Close returns, the candle-low stop, and the excursion of the path actually traded.

    ``stop`` is None for the open benchmark and for QQQ (a hold, not a stopped trade).
    ``entry_end`` is None for an entry at the session open: the whole first bar is then after the fill.
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
        if stop is not None and low <= stop:
            stopped = True
            stop_day = day_index
            worst_low = min(worst_low, stop)
            return True
        best_high = max(best_high, high)
        worst_low = min(worst_low, low)
        return False

    bars = day_bars if day_bars is not None else pd.DataFrame()
    if entry_end is None:
        path = bars
    else:
        path = bars.loc[bars.index > entry_end] if not bars.empty else bars
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


def open_entry(day_bars: Optional[pd.DataFrame], daily: Optional[pd.DataFrame], entry_day: pd.Timestamp) -> Optional[float]:
    """The session open: the first 15-minute bar's open, else the daily open."""
    if day_bars is not None and not day_bars.empty:
        price = float(day_bars.iloc[0].open)
        if price > 0:
            return price
    bar = _daily_on(daily, entry_day)
    if bar is None:
        return None
    price = float(bar.open)
    return price if price > 0 else None


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
    stop: the candle-low fill once it has been hit, otherwise the same close. The stop-hit rate
    is trade-level, over fills whose path through that horizon is known.
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


def build_stats(
    leader_rows: Sequence[Mapping],
    qqq_rows: Sequence[Mapping],
    weights: Optional[IntervalWeights] = None,
) -> dict:
    """Per-interval aggregates, the open buy, QQQ, and the best check-in on ``PRIMARY_HORIZON``."""
    weights = weights or IntervalWeights()
    leaders: dict[str, list[Mapping]] = {w: [] for w in (*WINDOW_IDS, OPEN_WINDOW)}
    for row in leader_rows:
        window = row.get("window")
        if window in leaders:
            leaders[window].append(row)
    qqq: dict[str, list[Mapping]] = {w: [] for w in (*WINDOW_IDS, OPEN_WINDOW)}
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
    open_stats = packed[OPEN_WINDOW]
    windows = {}
    for window in (*WINDOW_IDS, OPEN_WINDOW):
        body = {k: v for k, v in packed[window].items() if k != "_daily"}
        body["vs_open"] = {
            name: _paired_excess(packed[window]["_daily"][name], open_stats["_daily"][name]) for name, _, _ in HORIZONS
        }
        body["vs_qqq"] = {
            name: _paired_excess(packed[window]["_daily"][name], qqq_packed[window]["_daily"][name])
            for name, _, _ in HORIZONS
        }
        windows[window] = body

    best = _best_window(windows)
    qqq_body = {k: v for k, v in qqq_packed.get(best["window"] if best else "10:00", qqq_packed["10:00"]).items() if k != "_daily"}
    # QQQ displayed next to the intervals is the same-clock hold. Keep every window so the table can show one column.
    qqq_public = {}
    for window in (*WINDOW_IDS, OPEN_WINDOW):
        qqq_public[window] = {k: v for k, v in qqq_packed[window].items() if k != "_daily"}
    return {
        "windows": windows,
        "qqq": qqq_public,
        "best": best,
        "primary_horizon": PRIMARY_HORIZON,
        "weights": {"move": weights.move, "vs_qqq": weights.vs_qqq, "opening_range": weights.opening_range},
        "qqq_at_best": qqq_body,
    }


def _best_window(windows: Mapping[str, Mapping]) -> Optional[dict]:
    """Highest average close-to-close return at the primary horizon, then win rate. The open is not a candidate."""
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
        "vs_open": windows[window]["vs_open"].get(horizon),
        "vs_qqq": windows[window]["vs_qqq"].get(horizon),
    }


def definition_text(weights: Optional[IntervalWeights] = None) -> str:
    weights = weights or IntervalWeights()
    return (
        "Best at a check-in is the leader with the highest score from information known when that "
        f"15-minute candle closes: {weights.move:g} × the percent move from the session open, "
        f"{weights.vs_qqq:g} × that move minus QQQ's move, and {weights.opening_range:g} × where the "
        "close sits in the opening range so far (+1 at the high, −1 at the low). "
        "The entry is that candle's close. The stop is that candle's low."
    )


def iter_windows() -> Iterable[str]:
    return WINDOW_IDS
