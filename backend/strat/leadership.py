"""Leadership: trend quality, relative strength versus QQQ, and breakdown detection.

These are the inputs of the leadership-first score (see ``scoring.py``). Everything here is a pure function of daily
closes/highs and the 1M/3M/6M returns, so it works on a history cut off at any date (used by the backtest).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

import pandas as pd

from .perf import MOMENTUM_WEIGHTS, PERIODS, Perf

MA_PERIODS = (10, 20, 50)
SLOPE_BARS = 5  # a moving average is "rising" when it is above its value this many bars ago
HIGH_52W_BARS = 252
HIGH_6M_BARS = 126
MIN_HIGH_BARS = 60  # fewer bars than this and the "near highs" measures are skipped

# Relative strength versus QQQ: the outperformance (percentage points over QQQ's return) that earns full credit,
# per period. Lowered from +45 / +120 / +210 so a strong but not extreme chart is not stuck on partial credit.
FULL_EXCESS_PCT = {"1m": 20.0, "3m": 60.0, "6m": 100.0}
BENCHMARK = "QQQ"
# RS line = close / QQQ. A new 52-week high in the last few sessions is an alternative to the P90 percentile
# gate. The window is the same 252 sessions as the other 52-week reads. The ratio is computed on that window
# only and never stored: a second copy of the price cache does not fit a 512 MB dyno.
RS_LINE_RECENT = 5
RS_LINE_HIGH_FRACTION = 0.999  # at the high, or within 0.1% (float noise and a print that just tagged it)

# A leader needs at least this blended 1M/3M/6M return percentile among its peers (stocks vs stocks, ETFs vs ETFs):
# the top decile. The backtest favours this over P80 (see README).
LEADER_MIN_RS = 0.90
# The Leaders scan (and /api/scan?leaders_only=true) also needs a top score, strictly above this. It is a list filter
# only: leader_status / is_leader stay RS + trend, because the score itself is built from leader status and breakdown.
# The list also admits a name under P90 when its RS line versus QQQ made a 52-week high in the last 5 sessions
# (see rs_line_new_high), still with the trend intact and the score above this line.
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


def is_leader(rs: Optional[float], breakdown_level: str, min_rs: float = LEADER_MIN_RS) -> bool:
    return leader_status(rs, Breakdown(breakdown_level), min_rs) == LEADER


def rs_line_new_high(
    close: Optional[pd.Series],
    benchmark: Optional[pd.Series],
    *,
    recent: int = RS_LINE_RECENT,
    bars: int = HIGH_52W_BARS,
    fraction: float = RS_LINE_HIGH_FRACTION,
) -> bool:
    """True when ``close / benchmark`` made a 52-week high during the last ``recent`` sessions.

    Uses one 252-session window of the two close series already in memory and returns a bool. It does not
    build a frame or keep the ratio. ``False`` when the benchmark is missing or either side is shorter than
    a 52-week window, so a cold start (QQQ not loaded yet) still scans and simply does not open this gate.
    """
    if close is None or benchmark is None or len(close) < bars or len(benchmark) < bars:
        return False
    window = close.iloc[-bars:]
    aligned = benchmark.reindex(window.index)
    # One small array. Drop it when the function returns; do not attach it to a scan row.
    num = window.to_numpy(dtype="float64", copy=False)
    den = aligned.to_numpy(dtype="float64", copy=False)
    ratio = num / den
    finite = (ratio == ratio) & (ratio != float("inf")) & (ratio != float("-inf")) & (den > 0)
    valid = ratio[finite]
    # A handful of missing sessions (a holiday on one feed) still counts. Much less than a year does not.
    if len(valid) < bars - recent:
        return False
    recent_vals = valid[-recent:]
    peak = float(valid.max())
    if peak <= 0:
        return False
    return bool(float(recent_vals.max()) >= peak * fraction)


def in_leaders_scan(
    rs: Optional[float],
    breakdown_level: str,
    score: Optional[float],
    min_rs: float = LEADER_MIN_RS,
    min_score: float = LEADERS_MIN_SCORE,
    rs_line_high: bool = False,
) -> bool:
    """Listed by the Leaders scan.

    Trend not broken, score strictly above ``min_score`` (70.0 is out), and either relative strength at or
    above ``min_rs`` or — when ``min_rs`` has not been raised above the default P90 — an RS line versus QQQ
    that made a 52-week high in the last 5 sessions. ``is_leader`` stays RS + trend; this is only the list.
    """
    if score is None or score <= min_score or breakdown_level == BROKEN:
        return False
    if rs is not None and rs >= min_rs:
        return True
    return bool(rs_line_high) and min_rs <= LEADER_MIN_RS
