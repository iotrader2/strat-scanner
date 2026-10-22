"""Leadership: trend quality, relative strength versus QQQ, and breakdown detection.

These are the inputs of the leadership-first score (see ``scoring.py``). Everything here is a pure function of daily
closes/highs and the 1M/3M/6M returns, so it works on a history cut off at any date (used by the backtest).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

import pandas as pd

from .perf import MOMENTUM_WEIGHTS, PERIODS, Perf

MA_PERIODS = (10, 20, 50)
SLOPE_BARS = 5  # a moving average is "rising" when it is above its value this many bars ago
HIGH_52W_BARS = 252
HIGH_6M_BARS = 126
MIN_HIGH_BARS = 60  # fewer bars than this and the "near highs" measures are skipped

# Relative strength versus QQQ: the outperformance (percentage points over QQQ's return) that earns full credit,
# per period.
FULL_EXCESS_PCT = {"1m": 45.0, "3m": 120.0, "6m": 210.0}
BENCHMARK = "QQQ"

# A leader needs at least this blended 1M/3M/6M return percentile among its peers (stocks vs stocks, ETFs vs ETFs):
# the top decile. The backtest favours this over P80 (see README).
LEADER_MIN_RS = 0.90
# The Leaders scan (and /api/scan?leaders_only=true) also needs a top score, strictly above this. It is a list filter
# only: leader_status / is_leader stay RS + trend, because the score itself is built from leader status and breakdown.
LEADERS_MIN_SCORE = 70.0
# Breakdown thresholds (percent below the 6-month high).
WARN_DRAWDOWN_PCT = 12.0
BROKEN_DRAWDOWN_PCT = 25.0
# 1M return negative while the 3M/6M percentiles are still this high: strength that is rolling over.
ROLLOVER_LONG_RS = 0.75

LEADER = "leader"
WARNING = "warning"
BROKEN = "broken"
LAGGARD = "laggard"


@dataclass(frozen=True)
class Trend:
    """Moving-average structure and distance from the highs, as of the last bar."""

    price: float
    sma: dict[int, Optional[float]]
    rising: dict[int, Optional[bool]]
    off_52w_high_pct: Optional[float]  # percent below the 52-week high (0 at the high)
    off_6m_high_pct: Optional[float]
    bars: int

    def above(self, period: int) -> Optional[bool]:
        ma = self.sma.get(period)
        return None if ma is None else self.price > ma

    @property
    def stacked(self) -> bool:
        """Short averages above longer ones (10 > 20 > 50): a clean uptrend structure."""
        a, b, c = (self.sma.get(p) for p in MA_PERIODS)
        return a is not None and b is not None and c is not None and a > b > c


def trend_metrics(daily: pd.DataFrame) -> Optional[Trend]:
    """Trend structure of a daily OHLC frame; None when there is no usable close."""
    if daily is None or daily.empty or "close" not in daily:
        return None
    close = daily["close"].dropna()
    if close.empty:
        return None
    high = daily["high"].dropna() if "high" in daily else close
    n = len(close)
    price = float(close.iloc[-1])
    sma: dict[int, Optional[float]] = {}
    rising: dict[int, Optional[bool]] = {}
    for p in MA_PERIODS:
        sma[p] = float(close.iloc[-p:].mean()) if n >= p else None
        if n >= p + SLOPE_BARS:
            prior = float(close.iloc[-p - SLOPE_BARS : -SLOPE_BARS].mean())
            rising[p] = sma[p] > prior
        else:
            rising[p] = None

    def off_high(bars: int) -> Optional[float]:
        if n < MIN_HIGH_BARS:
            return None
        top = max(float(high.iloc[-bars:].max()), price)
        return round((top - price) / top * 100.0, 2) if top > 0 else None

    return Trend(price, sma, rising, off_high(HIGH_52W_BARS), off_high(HIGH_6M_BARS), n)


def qqq_excess(perf: Perf, qqq: Optional[Perf]) -> dict[str, Optional[float]]:
    """Return minus QQQ's return, per period, in percentage points (None when either side is missing)."""
    qqq = qqq or {}
    return {
        p: None if perf.get(p) is None or qqq.get(p) is None else round(perf[p] - qqq[p], 2) for p in PERIODS
    }


def long_term_rs(percentiles: Mapping[str, Optional[float]]) -> Optional[float]:
    """Blend of the 3M and 6M percentiles (the medium-term trend), used to spot a leader rolling over."""
    have = {p: percentiles.get(p) for p in ("3m", "6m") if percentiles.get(p) is not None}
    total = sum(MOMENTUM_WEIGHTS[p] for p in have)
    return sum(MOMENTUM_WEIGHTS[p] * v for p, v in have.items()) / total if total else None


@dataclass(frozen=True)
class Breakdown:
    level: str  # "none" | WARNING | BROKEN
    reasons: list[str] = field(default_factory=list)


def assess_breakdown(trend: Optional[Trend], perf: Perf, long_rs: Optional[float]) -> Breakdown:
    """Flag a leader that is losing its trend so it is demoted instead of ranked on stale 6M strength.

    *Broken*: price under the 50-day average, or 25%+ below the 6-month high.
    *Warning*: under the 20-day average, 12%+ below the 6-month high, or a 1M return that has turned negative while the
    3M/6M return percentiles are still high (strength rolling over).
    """
    if trend is None:
        return Breakdown("none")
    lost = {p for p in MA_PERIODS if trend.above(p) is False}
    dd = trend.off_6m_high_pct
    one_m = perf.get("1m")
    rollover = one_m is not None and one_m < 0 and long_rs is not None and long_rs >= ROLLOVER_LONG_RS
    broken: list[str] = []
    warn: list[str] = []
    if 50 in lost:
        broken.append("below the 50-day average")
    if dd is not None and dd >= BROKEN_DRAWDOWN_PCT:
        broken.append(f"{dd:.0f}% below the 6-month high")
    if 20 in lost:
        warn.append("below the 20-day average")
    if dd is not None and WARN_DRAWDOWN_PCT <= dd < BROKEN_DRAWDOWN_PCT:
        warn.append(f"{dd:.0f}% below the 6-month high")
    if rollover:
        extra = " with the 10/20-day averages lost" if {10, 20} <= lost else ""
        warn.append(f"1M {one_m:+.1f}% while 3M/6M strength is still high{extra}")
    if broken:
        return Breakdown(BROKEN, broken + [w for w in warn if w not in broken])
    if warn:
        return Breakdown(WARNING, warn)
    return Breakdown("none")


def leader_status(rs: Optional[float], breakdown: Breakdown, min_rs: float = LEADER_MIN_RS) -> str:
    """``leader`` (RS at or above the cut and trend intact, possibly with a warning), ``broken`` (RS high but the
    trend is gone) or ``laggard`` (below the RS cut)."""
    if rs is None or rs < min_rs:
        return LAGGARD
    return BROKEN if breakdown.level == BROKEN else LEADER


def nearest_trigger(price: float, weekly: Sequence[tuple[float, str]]) -> Optional[tuple[float, str]]:
    """Closest completed-week high above price for a name with no setup.

    ``weekly`` is ``(high, label)`` pairs, most recent completed week first.
    None when price is already above both (at highs).
    """
    above = [(h, label) for h, label in weekly if h > price]
    return min(above, key=lambda t: t[0]) if above else None


def is_leader(rs: Optional[float], breakdown_level: str, min_rs: float = LEADER_MIN_RS) -> bool:
    return leader_status(rs, Breakdown(breakdown_level), min_rs) == LEADER


def in_leaders_scan(
    rs: Optional[float], breakdown_level: str, score: Optional[float], min_rs: float = LEADER_MIN_RS,
    min_score: float = LEADERS_MIN_SCORE,
) -> bool:
    """Listed by the Leaders scan: marked leader (RS at or above ``min_rs``, trend not broken) and score strictly above
    ``min_score`` (70)."""
    return is_leader(rs, breakdown_level, min_rs) and score is not None and score > min_score
