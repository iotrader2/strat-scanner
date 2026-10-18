"""Change detection for the scan table: relative strength versus a week ago and fresh breakdown / leader transitions.

Everything is recomputed from the loaded history cut off at earlier sessions (the same way ``STRAT_AS_OF`` cuts the
cache), never from stored snapshots: at each prior session every symbol's 1M/3M/6M returns are measured on the history
up to that date and ranked against its peers on that date (stocks vs stocks, ETFs vs ETFs, themes vs themes), then the
blend and the breakdown assessment are the usual functions. The sessions are the QQQ trading calendar, so every symbol
is compared on the same dates. Only the prior dates in ``SNAPSHOT_OFFSETS`` are computed (4 extra passes), and the
peer distributions are built once per date and reused by every symbol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

import pandas as pd

from .leadership import (
    BENCHMARK,
    BROKEN,
    LEADER_MIN_RS,
    WARNING,
    assess_breakdown,
    long_term_rs,
    trend_metrics,
)
from .perf import MomentumRanks, Perf, period_returns

MIN_BARS = 30  # same floor as the scan itself

RS_LOOKBACK = 5  # sessions: "RS change" compares today's blended percentile with this many sessions earlier
STATE_LOOKBACK = 3  # sessions: a breakdown or leader transition is "new" if it happened within this many sessions
SNAPSHOT_OFFSETS = tuple(range(1, STATE_LOOKBACK + 1)) + (RS_LOOKBACK,)

SEVERITY = {"none": 0, WARNING: 1, BROKEN: 2}


@dataclass(frozen=True)
class PriorRanks:
    """Peer distributions as of one prior session."""

    offset: int  # sessions before the latest one
    date: pd.Timestamp
    ranks: MomentumRanks


def session_calendar(daily_by_symbol: Mapping[str, pd.DataFrame]) -> Optional[pd.DatetimeIndex]:
    """The trading sessions to step back through: QQQ's, else the longest history."""
    bench = daily_by_symbol.get(BENCHMARK)
    if bench is not None and len(bench) >= MIN_BARS:
        return pd.DatetimeIndex(bench.index)
    frames = [df for df in daily_by_symbol.values() if df is not None and len(df) >= MIN_BARS]
    if not frames:
        return None
    return pd.DatetimeIndex(max(frames, key=lambda df: (len(df), df.index[-1])).index)


def prior_ranks(
    calendar: Optional[Sequence[pd.Timestamp]],
    daily_by_group: Mapping[str, Mapping[str, pd.DataFrame]],
    offsets: Sequence[int] = SNAPSHOT_OFFSETS,
) -> dict[int, PriorRanks]:
    """Peer distributions at each prior session in ``offsets`` (offset 1 = the session before the latest).

    ``daily_by_group`` maps the peer group ("stock", "etf", "theme") to ``{symbol: daily frame}`` exactly as the scan
    ranks them today. Offsets beyond the calendar are skipped.
    """
    out: dict[int, PriorRanks] = {}
    if calendar is None:
        return out
    for k in offsets:
        if k >= len(calendar):
            continue
        date = pd.Timestamp(calendar[-1 - k])
        perf_by_group: dict[str, dict[str, Perf]] = {}
        for group, frames in daily_by_group.items():
            perfs = {}
            for sym, df in frames.items():
                close = df.close.loc[:date]
                if len(close) >= MIN_BARS:
                    perfs[sym] = period_returns(close)
            perf_by_group[group] = perfs
        out[k] = PriorRanks(k, date, MomentumRanks.from_perf(perf_by_group))
    return out


@dataclass(frozen=True)
class Snapshot:
    """A symbol's blended RS percentile and breakdown level as of a prior session."""

    offset: int
    date: str
    rs: Optional[float]
    level: Optional[str]  # None when there is not enough history at that date


def snapshot(kind: str, daily: pd.DataFrame, prior: PriorRanks, with_level: bool = True) -> Optional[Snapshot]:
    """The symbol as of ``prior.date``: history cut off there, ranked against the peers on that date."""
    sub = daily.loc[: prior.date]
    if len(sub) < MIN_BARS:
        return None
    perf = period_returns(sub.close)
    momentum = prior.ranks.momentum(kind, perf)
    level = None
    if with_level:
        level = assess_breakdown(trend_metrics(sub), perf, long_term_rs(momentum.percentiles)).level
    return Snapshot(prior.offset, prior.date.strftime("%Y-%m-%d"), momentum.blended, level)


def rs_points(rs: Optional[float]) -> Optional[int]:
    """A 0..1 percentile as whole percentile points, as the chip shows it ("RS 91")."""
    return None if rs is None else int(round(rs * 100))


def rs_change_points(rs: Optional[float], rs_prev: Optional[float]) -> Optional[int]:
    """Change in whole percentile points between the two chip values (positive = strengthening)."""
    now, then = rs_points(rs), rs_points(rs_prev)
    return None if now is None or then is None else now - then


def worsened(level: str, history: Sequence[Snapshot], today: str, lookback: int = STATE_LOOKBACK) -> Optional[dict]:
    """The breakdown transition that just happened, or None.

    ``level`` is today's breakdown level ("none" | "warning" | "broken"); ``history`` the prior snapshots. It is *new*
    when today's level is worse than the level on at least one of the last ``lookback`` sessions: the transition is
    dated at the first session of the current stretch at today's level or worse (``since``), coming from the level of
    the most recent less severe session (``from``). none -> warning, none -> broken and warning -> broken all count;
    a level that is merely unchanged or improving never does.
    """
    if SEVERITY.get(level, 0) == 0:
        return None
    by_offset = {s.offset: s for s in history if s.level is not None and s.offset <= lookback}
    for k in range(1, lookback + 1):
        snap = by_offset.get(k)
        if snap is None or SEVERITY[snap.level] >= SEVERITY[level]:
            continue
        earlier = by_offset.get(k - 1)
        return {"from": snap.level, "to": level, "since": earlier.date if earlier else today, "sessions_ago": k - 1}
    return None


def entered_leaders(
    rs: Optional[float], level: str, history: Sequence[Snapshot], today: str, gate: float = LEADER_MIN_RS,
    lookback: int = STATE_LOOKBACK,
) -> Optional[dict]:
    """A leader that crossed above the RS gate within the last ``lookback`` sessions, or None.

    Today: blended RS at or above ``gate`` with the trend not broken (the Leaders list). New when some session in the
    window was below the gate; ``since`` is the first session back above it and ``from_rs`` the RS just before.
    """
    if rs is None or rs < gate or level == BROKEN:
        return None
    by_offset = {s.offset: s for s in history if s.rs is not None and s.offset <= lookback}
    for k in range(1, lookback + 1):
        snap = by_offset.get(k)
        if snap is None or snap.rs >= gate:
            continue
        earlier = by_offset.get(k - 1)
        return {"since": earlier.date if earlier else today, "sessions_ago": k - 1, "from_rs": round(snap.rs, 4)}
    return None
