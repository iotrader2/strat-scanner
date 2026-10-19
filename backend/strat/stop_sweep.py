"""Stop sweep for the 10:30 rank-tie books.

The entry does not change: buy the 10:30 close after a 5-minute close above the 20 RMA, ordered by
the earliest cross, then leader rank, then the symbol. Every stop is set at 10:30 from data known
then and is never moved. A stop that is not strictly under the entry is skipped. A later name does
not fill that slot.

1R is the distance from the entry to that stop, so a tight stop turns the same dollar move into a
larger R. The percent result is the same-size view. Stop exits can also be filled 0.05% worse, with
the original stop still the risk unit.
"""

from __future__ import annotations

from statistics import median
from typing import Mapping, Optional, Sequence

import pandas as pd

from .adjust import apply_splits
from .data import load_splits
from .morning import (
    HORIZON_INDEX,
    HORIZONS,
    PCT_FIELD,
    RMA_LENGTH,
    _horizon_done,
    _mean,
    _rank_order_key,
    _split_session,
    first_stop_bar,
    format_clock,
    lod_outcome,
    realized_lod_r,
    realized_pct,
    rma_rank_cap,
    session_low_through,
    wilder_rma,
    window_end,
)
from .morning_store import all_leaders, load_bars

# Adverse fill on a stop exit, as a fraction of the exit price. 0.05% .
SLIPPAGE = 0.0005
# A stop is "near the top" when its day-3 R per trade is within this many R of the best.
NEAR_R = 0.05
ATR_LENGTH = 14
FAST_MINUTES = 30
# (id, family, label). The label is the column title.
CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("pct_025", "percent", "0.25%"),
    ("pct_050", "percent", "0.50%"),
    ("pct_075", "percent", "0.75%"),
    ("pct_100", "percent", "1.00%"),
    ("pct_150", "percent", "1.50%"),
    ("datr_010", "daily_atr", "0.10x daily ATR"),
    ("datr_015", "daily_atr", "0.15x daily ATR"),
    ("datr_020", "daily_atr", "0.20x daily ATR"),
    ("datr_025", "daily_atr", "0.25x daily ATR"),
    ("datr_033", "daily_atr", "0.33x daily ATR"),
    ("datr_050", "daily_atr", "0.50x daily ATR"),
    ("iatr_1", "intraday_atr", "1x 5-min ATR"),
    ("iatr_15", "intraday_atr", "1.5x 5-min ATR"),
    ("iatr_2", "intraday_atr", "2x 5-min ATR"),
    ("iatr_3", "intraday_atr", "3x 5-min ATR"),
    ("bar", "candle", "10:30 bar"),
    ("bars2", "candle", "Last 2 bars"),
    ("bars3", "candle", "Last 3 bars"),
    ("m15", "candle", "15-min low"),
    ("m30", "candle", "30-min low"),
    ("since", "candle", "Low since cross"),
    ("rma", "candle", "20 RMA"),
    ("rma_atr", "candle", "RMA - 0.1 ATR"),
    ("lod", "candle", "Low of day"),
)
_CANDIDATE_INDEX = {spec[0]: i for i, spec in enumerate(CANDIDATES)}
_LABEL = {spec[0]: spec[2] for spec in CANDIDATES}
_FAMILY = {spec[0]: spec[1] for spec in CANDIDATES}
_PERCENT = (("pct_025", 0.25), ("pct_050", 0.50), ("pct_075", 0.75), ("pct_100", 1.0), ("pct_150", 1.5))
_DAILY_ATR = (
    ("datr_010", 0.10),
    ("datr_015", 0.15),
    ("datr_020", 0.20),
    ("datr_025", 0.25),
    ("datr_033", 0.33),
    ("datr_050", 0.50),
)
_INTRADAY_ATR = (("iatr_1", 1.0), ("iatr_15", 1.5), ("iatr_2", 2.0), ("iatr_3", 3.0))
BOOKS = (("first", "First", 1), ("two", "First 2", 2))


def sweep_text() -> str:
    return (
        "First and First 2 of the 10:30 rank-tie book. The entry stays the 10:30 close after a "
        "5-minute bar has closed above the 20 RMA. The order is the earliest cross, then the leader "
        "rank, then the symbol. Only the stop changes. Each stop is set at 10:30 from prices known "
        "then and is never moved. A stop that is not strictly under the entry is skipped, and a later "
        "name does not take the slot. One R is the distance from the entry down to that stop. "
        "R per trade and total R size every fill to risk 1R. Average percent and total percent keep "
        "the same position size on every fill, so a tight stop does not inflate them."
    )


def noise_text() -> str:
    return (
        "These stops are judged on 5-minute bars. A very tight stop is sensitive to that bar size "
        "and to slippage: the low of a 5-minute bar can trade through a stop that a finer tape would "
        "have filled, and the order inside the bar is unknown. The slippage variant fills every stop "
        "exit 0.05% worse than the stop or the gap open. The risk unit stays the original stop, so a "
        "touch can book worse than -1R."
    )


def wilder_atr(high: Sequence[float], low: Sequence[float], close: Sequence[float], length: int = ATR_LENGTH) -> list[float]:
    """TradingView ``ta.atr``: Wilder smoothing of true range. The first value sits on bar ``length``."""
    n = len(close)
    out = [float("nan")] * n
    if n < length + 1 or length < 1:
        return out
    trs = [0.0] * n
    for i in range(1, n):
        trs[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    seed = sum(trs[1 : length + 1]) / length
    out[length] = seed
    prev = seed
    for i in range(length + 1, n):
        prev = (trs[i] + (length - 1) * prev) / length
        out[i] = prev
    return out


def _finite(value) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def daily_atr_prior(daily: Optional[pd.DataFrame], day: str, length: int = ATR_LENGTH) -> Optional[float]:
    """Wilder ATR(14) on daily bars that closed before ``day``. Today's range is not in it."""
    if daily is None or daily.empty:
        return None
    start = pd.Timestamp(day).normalize()
    prior = daily.loc[daily.index < start]
    if len(prior) < length + 1:
        return None
    values = wilder_atr(
        [float(v) for v in prior["high"]],
        [float(v) for v in prior["low"]],
        [float(v) for v in prior["close"]],
        length,
    )
    return _finite(values[-1])


def intraday_atr_at(bars: Optional[pd.DataFrame], end: pd.Timestamp, length: int = ATR_LENGTH) -> Optional[float]:
    """Wilder ATR(14) of 5-minute bars through ``end``, including the bar that ends then."""
    if bars is None or bars.empty or end not in bars.index:
        return None
    frame = bars.loc[bars.index <= end]
    if len(frame) < length + 1:
        return None
    values = wilder_atr(
        [float(v) for v in frame["high"]],
        [float(v) for v in frame["low"]],
        [float(v) for v in frame["close"]],
        length,
    )
    return _finite(values[-1])


def rma_value_at(bars: Optional[pd.DataFrame], end: pd.Timestamp, length: int = RMA_LENGTH) -> Optional[float]:
    """20 RMA at ``end``, after that bar's close has updated the average."""
    if bars is None or bars.empty or end not in bars.index:
        return None
    prior, today = _split_session(bars, end)
    if today.empty:
        return None
    combined = pd.concat([prior, today]) if not prior.empty else today
    values = wilder_rma([float(v) for v in combined["close"]], length)
    return _finite(values[-1])


def _lows_at(bars: Optional[pd.DataFrame], day: str, labels: Sequence[str]) -> Optional[float]:
    if bars is None or bars.empty:
        return None
    lows = []
    for label in labels:
        stamp = window_end(day, label)
        if stamp not in bars.index:
            return None
        low = _finite(bars.loc[stamp].low)
        if low is None:
            return None
        lows.append(low)
    return min(lows) if lows else None


def _low_since_cross(bars: Optional[pd.DataFrame], day: str, cross_time: Optional[str], end: pd.Timestamp) -> Optional[float]:
    if bars is None or bars.empty or not cross_time:
        return None
    start = window_end(day, str(cross_time))
    if start not in bars.index:
        return None
    chunk = bars.loc[(bars.index >= start) & (bars.index <= end)]
    if chunk.empty:
        return None
    return _finite(chunk["low"].min())


def stop_levels(
    day: str,
    entry: float,
    bars: Optional[pd.DataFrame],
    daily: Optional[pd.DataFrame],
    cross_time: Optional[str],
) -> dict[str, Optional[float]]:
    """Every candidate price. None when the input is missing. The caller skips a price that is not under the entry."""
    end = window_end(day, "10:30")
    daily_atr = daily_atr_prior(daily, day)
    intra = intraday_atr_at(bars, end)
    rma = rma_value_at(bars, end)
    levels: dict[str, Optional[float]] = {}
    for sid, pct in _PERCENT:
        levels[sid] = entry * (1.0 - pct / 100.0) if entry > 0 else None
    for sid, mult in _DAILY_ATR:
        levels[sid] = None if daily_atr is None else entry - mult * daily_atr
    for sid, mult in _INTRADAY_ATR:
        levels[sid] = None if intra is None else entry - mult * intra
    levels["bar"] = _lows_at(bars, day, ("10:30",))
    levels["bars2"] = _lows_at(bars, day, ("10:25", "10:30"))
    levels["bars3"] = _lows_at(bars, day, ("10:20", "10:25", "10:30"))
    levels["m15"] = _lows_at(bars, day, ("10:20", "10:25", "10:30"))
    levels["m30"] = _lows_at(bars, day, ("10:05", "10:10", "10:15", "10:20", "10:25", "10:30"))
    levels["since"] = _low_since_cross(bars, day, cross_time, end)
    levels["rma"] = rma
    levels["rma_atr"] = None if rma is None or daily_atr is None else rma - 0.1 * daily_atr
    levels["lod"] = session_low_through(bars, end)
    return levels


def evaluate_stop(
    *,
    entry: float,
    stop: Optional[float],
    bars: Optional[pd.DataFrame],
    entry_end: pd.Timestamp,
    daily: Optional[pd.DataFrame],
    entry_day: pd.Timestamp,
    forward: Sequence[pd.Timestamp],
) -> dict:
    """One stop. ``skipped`` is 1 when the stop is missing or not strictly under the entry."""
    level = _finite(stop)
    if level is None or entry <= 0 or not (level < entry):
        return {
            "entry_price": entry,
            "stop_price": level,
            "stop_pct": None if level is None or entry <= 0 else (entry - level) / entry * 100.0,
            "eod_pct": None,
            "d1_pct": None,
            "d2_pct": None,
            "d3_pct": None,
            "d4_pct": None,
            "d5_pct": None,
            "stopped": 0,
            "stop_day": None,
            "exit_pct": None,
            "gapped": 0,
            "mfe_pct": None,
            "fast_stop": 0,
            "skipped": 1,
        }
    body = lod_outcome(
        entry=entry,
        stop=level,
        day_bars=bars,
        entry_end=entry_end,
        daily=daily,
        entry_day=entry_day,
        forward_days=forward,
    )
    hit = first_stop_bar(bars, entry_end, level, forward)
    deadline = entry_end + pd.Timedelta(minutes=FAST_MINUTES)
    fast = bool(hit) and int(hit["day_index"]) == 0 and pd.Timestamp(hit["ts"]) <= deadline
    body["fast_stop"] = int(fast)
    body["skipped"] = 0
    return body


def sweeps_for_day(
    day: str,
    leaders: Sequence[Mapping],
    intraday: Mapping[str, pd.DataFrame],
    daily: Mapping[str, pd.DataFrame],
    calendar: Sequence[str],
    ranks: Optional[Mapping[str, int]] = None,
) -> list[dict]:
    """First and first-two rank-tie names, each with every stop. Slot 1 is the first name."""
    score = {day: {sym: int(rank) for sym, rank in (ranks or {}).items()}}
    dated = []
    for row in leaders:
        if row.get("rule") != "rma1030":
            continue
        dated.append({**row, "date": day})
    chosen = sorted(rma_rank_cap(dated, score, 2), key=lambda row: _rank_order_key(row, score))
    forward = [pd.Timestamp(item) for item in calendar if item > day][:5]
    entry_day = pd.Timestamp(day)
    end = window_end(day, "10:30")
    rows = []
    for slot, row in enumerate(chosen, start=1):
        symbol = str(row["symbol"])
        bars = intraday.get(symbol)
        entry = float(row["entry_price"])
        levels = stop_levels(day, entry, bars, daily.get(symbol), row.get("cross_time"))
        for sid, _family, _label in CANDIDATES:
            outcome = evaluate_stop(
                entry=entry,
                stop=levels.get(sid),
                bars=bars,
                entry_end=end,
                daily=daily.get(symbol),
                entry_day=entry_day,
                forward=forward,
            )
            rows.append(
                {
                    "date": day,
                    "symbol": symbol,
                    "stop_id": sid,
                    "slot": slot,
                    "cross_time": row.get("cross_time"),
                    **outcome,
                }
            )
    return rows


def slip_pct(row: Mapping, horizon: str) -> Optional[float]:
    """Stop-aware percent. A stop exit is 0.05% worse than the raw exit. A hold is unchanged."""
    idx = HORIZON_INDEX[horizon]
    stop_day = row.get("stop_day")
    if row.get("stopped") and stop_day is not None and int(stop_day) <= idx and row.get("exit_pct") is not None:
        entry = float(row["entry_price"])
        if entry <= 0:
            return None
        exit_price = entry * (1.0 + float(row["exit_pct"]) / 100.0)
        slipped = exit_price * (1.0 - SLIPPAGE)
        return (slipped / entry - 1.0) * 100.0
    return realized_pct(row, horizon)


def slip_r(row: Mapping, horizon: str) -> Optional[float]:
    pct = slip_pct(row, horizon)
    risk = row.get("stop_pct")
    if pct is None or risk is None or float(risk) <= 0:
        return None
    return pct / float(risk)


def _summarize_variant(sid: str, family: str, label: str, rows: Sequence[Mapping]) -> dict:
    fills = [row for row in rows if not int(row.get("skipped") or 0)]
    risks = [float(row["stop_pct"]) for row in fills if row.get("stop_pct") is not None and float(row["stop_pct"]) > 0]
    fast = sum(int(row.get("fast_stop") or 0) for row in fills)
    by_date: dict[str, list] = {}
    for row in fills:
        by_date.setdefault(str(row.get("date")), []).append(row)
    horizons = {}
    for name, _idx, _field in HORIZONS:
        trade_r: list[float] = []
        trade_pct: list[float] = []
        slip_rs: list[float] = []
        slip_pcts: list[float] = []
        mfes: list[float] = []
        stopped_n = 0
        gaps = 0
        resolved = 0
        days = 0
        for group in by_date.values():
            if not _horizon_done(group, name):
                continue
            morning = False
            for row in group:
                pct = realized_pct(row, name)
                r_value = realized_lod_r(row, name)
                if pct is None or r_value is None:
                    continue
                morning = True
                resolved += 1
                trade_pct.append(pct)
                trade_r.append(r_value)
                slipped = slip_pct(row, name)
                slipped_r = slip_r(row, name)
                if slipped is not None:
                    slip_pcts.append(slipped)
                if slipped_r is not None:
                    slip_rs.append(slipped_r)
                mfe = row.get("mfe_pct")
                risk = row.get("stop_pct")
                if mfe is not None and risk is not None and float(risk) > 0:
                    mfes.append(float(mfe) / float(risk))
                stop_day = row.get("stop_day")
                if row.get("stopped") and stop_day is not None and int(stop_day) <= HORIZON_INDEX[name]:
                    stopped_n += 1
                    if row.get("gapped"):
                        gaps += 1
            if morning:
                days += 1
        horizons[name] = {
            "n_days": days,
            "n_trades": len(trade_r),
            "r_per_trade": _mean(trade_r),
            "total_r": sum(trade_r) if trade_r else None,
            "avg_pct": _mean(trade_pct),
            "total_pct": sum(trade_pct) if trade_pct else None,
            "win_rate": (sum(v > 0 for v in trade_pct) / len(trade_pct)) if trade_pct else None,
            "stop_hit_rate": (stopped_n / resolved) if resolved else None,
            "gap_count": gaps,
            "avg_mfe": _mean(mfes),
            "median_r": float(median(trade_r)) if trade_r else None,
            "best_r": max(trade_r) if trade_r else None,
            "worst_r": min(trade_r) if trade_r else None,
            "slip_r_per_trade": _mean(slip_rs),
            "slip_total_r": sum(slip_rs) if slip_rs else None,
            "slip_avg_pct": _mean(slip_pcts),
            "slip_total_pct": sum(slip_pcts) if slip_pcts else None,
        }
    return {
        "id": sid,
        "label": label,
        "family": family,
        "n_considered": len(rows),
        "n_skipped": sum(int(row.get("skipped") or 0) for row in rows),
        "n_fills": len(fills),
        "avg_stop_pct": _mean(risks),
        "fast_stop_rate": (fast / len(fills)) if fills else None,
        "horizons": horizons,
    }


def _d3(stop: Mapping) -> Mapping:
    return (stop.get("horizons") or {}).get("d3") or {}


def _rank_ids(stops: Mapping[str, Mapping], key: str) -> list[str]:
    ranked = []
    for sid, stop in stops.items():
        value = _d3(stop).get(key)
        trades = _d3(stop).get("n_trades") or 0
        if value is None or not trades:
            continue
        width = stop.get("avg_stop_pct")
        ranked.append((float(value), -(float(width) if width is not None else 1e9), -_CANDIDATE_INDEX[sid], sid))
    ranked.sort(reverse=True)
    return [item[3] for item in ranked]


def _tightest(stops: Mapping[str, Mapping], order: Sequence[str]) -> Optional[str]:
    """Smallest average stop among variants within ``NEAR_R`` of the best day-3 R per trade."""
    if not order:
        return None
    best = _d3(stops[order[0]]).get("r_per_trade")
    if best is None:
        return None
    near = [sid for sid in order if (_d3(stops[sid]).get("r_per_trade") or -1e9) >= float(best) - NEAR_R]
    near.sort(key=lambda sid: (
        float(stops[sid]["avg_stop_pct"]) if stops[sid].get("avg_stop_pct") is not None else 1e9,
        -float(_d3(stops[sid]).get("r_per_trade") or -1e9),
        _CANDIDATE_INDEX[sid],
    ))
    return near[0] if near else None


def build_sweep_stats(rows: Sequence[Mapping]) -> dict:
    """First is slot 1. First 2 is slots 1 and 2. Ranks are by day-3 R per trade and by total R."""
    books = {}
    for book_id, label, limit in BOOKS:
        subset = [row for row in rows if int(row.get("slot") or 0) <= limit]
        stops = {}
        for sid, family, lab in CANDIDATES:
            mine = [row for row in subset if row.get("stop_id") == sid]
            stops[sid] = _summarize_variant(sid, family, lab, mine)
        order = _rank_ids(stops, "r_per_trade")
        order_total = _rank_ids(stops, "total_r")
        books[book_id] = {
            "id": book_id,
            "label": label,
            "order": order,
            "order_total": order_total,
            "best_r": order[0] if order else None,
            "best_total": order_total[0] if order_total else None,
            "tight": _tightest(stops, order),
            "stops": stops,
        }
    return {
        "books": books,
        "book_order": [book_id for book_id, _label, _limit in BOOKS],
        "candidates": [{"id": sid, "family": family, "label": label} for sid, family, label in CANDIDATES],
        "near_r": NEAR_R,
        "slippage_pct": SLIPPAGE * 100.0,
        "definition": sweep_text(),
        "noise": noise_text(),
    }


def rank_first_candidates(
    rows: Sequence[Mapping],
    score_ranks: Optional[Mapping] = None,
    *,
    exclude_symbols: Sequence[str] = ("CRWD",),
    target_r: Optional[float] = None,
) -> list[dict]:
    """Rank-tie first fills worth writing up, best first.

    CRWD and the single best day-3 R are left out. Winners come before losers. A morning with
    another name on the same cross bar comes before a unique cross. Closer to the book average
    comes before a far winner. The most recent breaks a tie.
    """
    chosen = rma_rank_cap([row for row in rows if row.get("rule") in (None, "rma1030")], score_ranks, 1)
    by_day: dict[str, list] = {}
    for row in rows:
        if row.get("rule") not in (None, "rma1030"):
            continue
        by_day.setdefault(str(row.get("date")), []).append(row)
    scored = []
    for row in chosen:
        if row.get("d5_pct") is None:
            continue
        result = realized_lod_r(row, "d3")
        if result is None:
            continue
        scored.append((row, float(result)))
    if not scored:
        return []
    book_avg = float(target_r) if target_r is not None else sum(item[1] for item in scored) / len(scored)
    best_r = max(item[1] for item in scored)
    best_row = min((item[0] for item in scored if item[1] == best_r), key=lambda row: str(row.get("date")))
    excluded = {str(symbol) for symbol in exclude_symbols}
    pool = []
    for row, result in scored:
        if str(row.get("symbol")) in excluded or result >= best_r - 1e-9:
            continue
        day = str(row.get("date"))
        cross = str(row.get("cross_time") or "")
        tied = [
            other
            for other in by_day.get(day, [])
            if other.get("symbol") != row.get("symbol") and str(other.get("cross_time") or "") == cross and cross
        ]
        pool.append((row, result, tied))
    pool.sort(key=lambda item: (
        0 if item[1] > 0 else 1,
        0 if item[2] else 1,
        abs(item[1] - book_avg),
        -int(str(item[0].get("date")).replace("-", "")),
    ))
    return [
        {
            "row": row,
            "day3_r": result,
            "book_avg_r": book_avg,
            "best_r": best_r,
            "best_date": str(best_row.get("date")),
            "best_symbol": str(best_row.get("symbol")),
            "n": len(scored),
            "tied": tied,
        }
        for row, result, tied in pool
    ]


def _clock_label(value: Optional[str]) -> str:
    if not value or ":" not in str(value):
        return value or "—"
    hour, minute = str(value).split(":", 1)
    return format_clock(int(hour) * 60 + int(minute)) or str(value)


def _path_rows(row: Mapping, entry: float, risk_pct: Optional[float], horizon_days: Sequence[tuple[str, str]]) -> list[dict]:
    out = []
    for horizon, stamp in horizon_days:
        close_pct = row.get(PCT_FIELD[horizon])
        close_pct = None if close_pct is None else float(close_pct)
        close_r = None if close_pct is None or risk_pct is None or float(risk_pct) <= 0 else close_pct / float(risk_pct)
        close = None if close_pct is None else entry * (1.0 + close_pct / 100.0)
        out.append(
            {
                "horizon": horizon,
                "date": stamp,
                "close": close,
                "close_pct": close_pct,
                "close_r": close_r,
                "booked_pct": realized_pct(row, horizon),
                "booked_r": realized_lod_r(row, horizon),
            }
        )
    return out


def _stop_hit(bars, entry_end, stop, day: str, forward: Sequence[str]) -> Optional[dict]:
    if stop is None or bars is None:
        return None
    hit = first_stop_bar(bars, entry_end, float(stop), [pd.Timestamp(item) for item in forward])
    if not hit:
        return None
    offset = int(hit["day_index"])
    if offset == 0:
        session = day
    elif offset - 1 < len(forward):
        session = forward[offset - 1]
    else:
        session = None
    return {
        "session": session,
        "clock": format_clock(pd.Timestamp(hit["ts"]).hour * 60 + pd.Timestamp(hit["ts"]).minute),
        "offset": offset,
        "gapped": bool(hit["gapped"]),
        "open": float(hit["open"]),
        "low": float(hit["low"]),
    }


def describe_rank_example(
    picked: Mapping,
    day_rows: Sequence[Mapping],
    leaders: Sequence[Mapping],
    bars: Optional[pd.DataFrame],
    forward: Sequence[str],
    sweep_rows: Sequence[Mapping],
    tight_id: Optional[str],
) -> dict:
    """One rank-tie first morning, plus the sweep's tight stop on that same fill."""
    from .morning import rma_at

    row = picked["row"]
    day = str(row["date"])
    symbol = str(row["symbol"])
    by_symbol = {str(item["symbol"]): item for item in leaders if str(item.get("date")) == day}
    leader = by_symbol.get(symbol) or {}
    entry = float(row["entry_price"])
    stop = _finite(row.get("stop_price"))
    risk_pct = _finite(row.get("stop_pct"))
    entry_end = window_end(day, "10:30")
    reading = rma_at(bars, entry_end) if bars is not None else None
    cross_close = None
    cross_rma = None
    if reading is not None:
        _ts, cross_close, cross_rma = reading
    score = {str(item["symbol"]): int(item["rank"]) for item in by_symbol.values()}
    cross = str(row.get("cross_time") or "")
    tied = []
    for other in day_rows:
        if other.get("symbol") == symbol or str(other.get("cross_time") or "") != cross or not cross:
            continue
        other_leader = by_symbol.get(str(other["symbol"])) or {}
        tied.append(
            {
                "symbol": str(other["symbol"]),
                "name": other_leader.get("name") or str(other["symbol"]),
                "rank": score.get(str(other["symbol"]), other_leader.get("rank")),
                "cross_time": other.get("cross_time"),
            }
        )
    tied.sort(key=lambda item: (int(item["rank"]) if item.get("rank") is not None else 10**9, item["symbol"]))
    rank = score.get(symbol, leader.get("rank"))
    clock = _clock_label(cross)
    if tied:
        others = ", ".join(f"{item['symbol']} rank {item['rank']}" for item in tied)
        why = (
            f"{len(tied) + 1} names crossed on the bar ending {clock}. "
            f"{symbol} is first among them because leader rank {rank} is the best on that bar. "
            f"The others on that bar: {others}."
        )
    else:
        why = f"{symbol} is the only name that crossed at {clock}, so the rank order takes it ahead of every later cross."
    symbol_first = sorted(day_rows, key=lambda item: (int(item.get("rank") or 10**9), str(item.get("symbol"))))
    symbol_first_name = str(symbol_first[0]["symbol"]) if symbol_first else None
    horizon_days = [("eod", day)] + [(name, forward[i]) for i, (name, _idx, _field) in enumerate(HORIZONS[1:]) if i < len(forward)]
    hit = _stop_hit(bars, entry_end, stop, day, forward) if int(row.get("stopped") or 0) else None
    tight = _tight_on_trade(sweep_rows, day, symbol, tight_id, entry, bars, entry_end, forward, horizon_days)
    return {
        "date": day,
        "symbol": symbol,
        "name": leader.get("name") or symbol,
        "leader_rank": rank,
        "cross_time": clock,
        "cross_close": cross_close,
        "cross_rma": cross_rma,
        "tied": tied,
        "why": why,
        "symbol_first": symbol_first_name,
        "entry": entry,
        "stop": stop,
        "stop_pct": risk_pct,
        "risk": None if stop is None else entry - stop,
        "stopped": int(row.get("stopped") or 0),
        "gapped": int(row.get("gapped") or 0),
        "hit": hit,
        "day3_r": picked.get("day3_r"),
        "book_avg_r": picked.get("book_avg_r"),
        "best_r": picked.get("best_r"),
        "best_date": picked.get("best_date"),
        "best_symbol": picked.get("best_symbol"),
        "n": picked.get("n"),
        "path": _path_rows(row, entry, risk_pct, horizon_days),
        "tight": tight,
    }


def _tight_on_trade(sweep_rows, day, symbol, tight_id, entry, bars, entry_end, forward, horizon_days) -> Optional[dict]:
    if not tight_id:
        return None
    match = [
        row for row in sweep_rows
        if str(row.get("date")) == day and str(row.get("symbol")) == symbol and row.get("stop_id") == tight_id
    ]
    if not match:
        return {"id": tight_id, "label": _LABEL.get(tight_id, tight_id), "missing": True}
    row = match[0]
    stop = _finite(row.get("stop_price"))
    risk_pct = _finite(row.get("stop_pct"))
    skipped = int(row.get("skipped") or 0)
    hit = None if skipped or not int(row.get("stopped") or 0) else _stop_hit(bars, entry_end, stop, day, forward)
    return {
        "id": tight_id,
        "label": _LABEL.get(tight_id, tight_id),
        "missing": False,
        "skipped": skipped,
        "stop": stop,
        "stop_pct": risk_pct,
        "risk": None if stop is None else entry - stop,
        "stopped": int(row.get("stopped") or 0),
        "gapped": int(row.get("gapped") or 0),
        "fast_stop": int(row.get("fast_stop") or 0),
        "hit": hit,
        "day3_r": realized_lod_r(row, "d3"),
        "day3_pct": realized_pct(row, "d3"),
        "path": [] if skipped else _path_rows(row, entry, risk_pct if risk_pct and risk_pct > 0 else None, horizon_days),
    }


def _calendar() -> list[str]:
    from . import data

    with data.connect() as conn:
        rows = conn.execute("SELECT date FROM bars WHERE symbol = 'QQQ' ORDER BY date").fetchall()
    return [row[0] for row in rows]


def load_rank_example(
    single_rows: Sequence[Mapping],
    score_ranks: Optional[Mapping],
    sweep_rows: Sequence[Mapping],
    tight_id: Optional[str],
    leaders: Optional[Sequence[Mapping]] = None,
    book_avg: Optional[float] = None,
) -> Optional[dict]:
    """The worked rank-tie morning. Prefers a fill the tight stop can actually take."""
    candidates = rank_first_candidates(single_rows, score_ranks, target_r=book_avg)
    if not candidates:
        return None
    chosen = candidates[0]
    if tight_id:
        for item in candidates:
            row = item["row"]
            taken = any(
                str(other.get("date")) == str(row.get("date"))
                and str(other.get("symbol")) == str(row.get("symbol"))
                and other.get("stop_id") == tight_id
                and not int(other.get("skipped") or 0)
                for other in sweep_rows
            )
            if taken:
                chosen = item
                break
    row = chosen["row"]
    day = str(row["date"])
    symbol = str(row["symbol"])
    day_rows = [item for item in single_rows if str(item.get("date")) == day and item.get("rule") in (None, "rma1030")]
    leader_rows = list(leaders) if leaders is not None else all_leaders()
    start = (pd.Timestamp(day) - pd.Timedelta(days=40)).strftime("%Y-%m-%d")
    end = (pd.Timestamp(day) + pd.Timedelta(days=21)).strftime("%Y-%m-%d")
    raw = load_bars([symbol], start, end, interval="5m").get(symbol)
    bars = None if raw is None else apply_splits(raw, load_splits().get(symbol, ()), end)
    forward = [item for item in _calendar() if item > day][:5]
    return describe_rank_example(chosen, day_rows, leader_rows, bars, forward, sweep_rows, tight_id)
