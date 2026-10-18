"""Price performance (1/3/6 months) and the percentile-based relative momentum behind the Momentum score component."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Mapping, Optional

import pandas as pd

PERIODS = ("1m", "3m", "6m")
PERIOD_MONTHS = {"1m": 1, "3m": 3, "6m": 6}
PERIOD_LABELS = {"1m": "1M", "3m": "3M", "6m": "6M"}

# Blend of the three percentile ranks. 3M and 6M carry most of the weight (the medium-term trend); 1M adds the
# recent turn without letting a one-month spike dominate. The weights sum to 1.
MOMENTUM_WEIGHTS = {"1m": 0.20, "3m": 0.40, "6m": 0.40}

# A return needs history reaching back this close to the period start (calendar days of slack for weekends/holidays).
START_TOLERANCE_DAYS = 5

Perf = dict[str, Optional[float]]


def period_returns(close: pd.Series) -> Perf:
    """Percent price return over the last 1, 3 and 6 calendar months, to the latest close.

    The base is the last close on or before the date one/three/six months before the latest bar; ``None`` when the
    history does not reach back that far.
    """
    out: Perf = {p: None for p in PERIODS}
    close = close.dropna()
    if close.empty:
        return out
    index = close.index
    values = close.to_numpy(dtype=float)
    last_date = index[-1]
    last = float(values[-1])
    for period, months in PERIOD_MONTHS.items():
        start = last_date - pd.DateOffset(months=months)
        if index[0] > start + pd.Timedelta(days=START_TOLERANCE_DAYS):
            continue
        before = index.searchsorted(start, side="right")  # bars on or before the start date
        base = float(values[before - 1]) if before else float(values[0])
        if base > 0:
            out[period] = round((last / base - 1.0) * 100.0, 2)
    return out


def blend(percentiles: Mapping[str, Optional[float]]) -> Optional[float]:
    """Weighted blend (0..1) of the available period percentiles; weights are renormalized when a period is missing."""
    have = {p: v for p, v in percentiles.items() if v is not None and p in MOMENTUM_WEIGHTS}
    total = sum(MOMENTUM_WEIGHTS[p] for p in have)
    if total <= 0:
        return None
    return sum(MOMENTUM_WEIGHTS[p] * v for p, v in have.items()) / total


@dataclass(frozen=True)
class Momentum:
    """One symbol's returns, their percentile ranks within its peer group, and the blended 0..1 rank."""

    group: str  # "stock" | "etf" | "theme"
    returns: dict[str, Optional[float]]
    percentiles: dict[str, Optional[float]]
    peers: dict[str, int]
    blended: Optional[float]


class MomentumRanks:
    """Return distributions per peer group (stocks vs stocks, ETFs vs ETFs, themes vs themes)."""

    def __init__(self, values: Mapping[str, Mapping[str, list[float]]]):
        self._values = {g: {p: sorted(v) for p, v in per.items()} for g, per in values.items()}

    @classmethod
    def from_perf(cls, perf_by_group: Mapping[str, Mapping[str, Perf]]) -> "MomentumRanks":
        values: dict[str, dict[str, list[float]]] = {}
        for group, perfs in perf_by_group.items():
            values[group] = {p: [r[p] for r in perfs.values() if r.get(p) is not None] for p in PERIODS}
        return cls(values)

    def percentile(self, group: str, period: str, value: Optional[float]) -> Optional[float]:
        """Percentile rank (0..1, ties share the middle) of ``value`` among the group's returns for ``period``."""
        if value is None:
            return None
        ordered = self._values.get(group, {}).get(period, [])
        if not ordered:
            return None
        less = bisect_left(ordered, value)
        equal = bisect_right(ordered, value) - less
        return (less + 0.5 * equal) / len(ordered)

    def peers(self, group: str, period: str) -> int:
        return len(self._values.get(group, {}).get(period, []))

    def momentum(self, group: str, perf: Perf) -> Momentum:
        percentiles = {p: self.percentile(group, p, perf.get(p)) for p in PERIODS}
        return Momentum(
            group=group,
            returns={p: perf.get(p) for p in PERIODS},
            percentiles=percentiles,
            peers={p: self.peers(group, p) for p in PERIODS},
            blended=blend(percentiles),
        )
