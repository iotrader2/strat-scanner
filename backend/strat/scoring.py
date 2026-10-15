"""Actionability score for long Strat setups (0-100, higher is better)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional

from .candles import Setup, TimeframeState

TF_NAMES = {"M": "Monthly", "W": "Weekly", "D": "Daily"}

CONTINUITY_POINTS = {"M": 15.0, "W": 15.0, "D": 8.0}
FULL_CONTINUITY_BONUS = 10.0

# Pending (not yet triggered) setups are the most actionable; higher timeframes weigh more.
SETUP_POINTS = {
    "inside": {"M": 22.0, "W": 18.0, "D": 12.0},
    "2-1-2-pending": {"M": 24.0, "W": 20.0, "D": 14.0},
    "3-1-2-pending": {"M": 24.0, "W": 20.0, "D": 14.0},
    "hammer": {"M": 18.0, "W": 15.0, "D": 10.0},
    "2-1-2": {"M": 12.0, "W": 10.0, "D": 7.0},
    "3-1-2": {"M": 12.0, "W": 10.0, "D": 7.0},
    "1-2-2": {"M": 10.0, "W": 8.0, "D": 6.0},
    "2D-2U": {"M": 9.0, "W": 7.0, "D": 5.0},
    "hammer-triggered": {"M": 9.0, "W": 7.0, "D": 5.0},
}
MAX_SETUP_POINTS = 28.0
PROXIMITY_POINTS = 15.0
PROXIMITY_WINDOW_PCT = 5.0
LIQUIDITY_POINTS = 10.0
# Names whose average daily range is this tight are usually pinned by a pending deal.
MIN_ATR_PCT = 0.5
PINNED_PENALTY = 0.5


@dataclass
class ScoredSetup:
    tf: str
    setup: Setup
    points: float


@dataclass
class Score:
    score: float
    primary: Optional[ScoredSetup]
    setups: list[ScoredSetup]
    reasons: list[str]
    full_continuity: bool
    mw_green: bool
    trigger_distance_pct: Optional[float]


def trigger_distance_pct(price: float, trigger: float) -> float:
    """Percent the price must rise to reach the trigger (negative once through it)."""
    return (trigger - price) / price * 100.0


def proximity_points(dist_pct: Optional[float], triggered: bool) -> float:
    if dist_pct is None:
        return 0.0
    if triggered or dist_pct <= 0:
        return PROXIMITY_POINTS * 0.5
    return PROXIMITY_POINTS * max(0.0, 1.0 - dist_pct / PROXIMITY_WINDOW_PCT)


def liquidity_points(avg_dollar_volume: float, floor: float = 50e6, ceiling: float = 5e9) -> float:
    if avg_dollar_volume <= floor:
        return 0.0
    frac = math.log10(avg_dollar_volume / floor) / math.log10(ceiling / floor)
    return LIQUIDITY_POINTS * min(1.0, frac)


def score_symbol(
    states: Mapping[str, Optional[TimeframeState]],
    price: float,
    avg_dollar_volume: float,
    atr_pct: Optional[float] = None,
) -> Score:
    reasons: list[str] = []
    total = 0.0

    colors = {tf: (s.color if s else None) for tf, s in states.items()}
    green = [tf for tf in ("M", "W", "D") if colors.get(tf) == "green"]
    for tf in green:
        total += CONTINUITY_POINTS[tf]
    full = len(green) == 3
    mw_green = "M" in green and "W" in green
    if full:
        total += FULL_CONTINUITY_BONUS
        reasons.append("Full continuity M+W+D green")
    elif mw_green:
        reasons.append("M+W green")
    elif green:
        reasons.append("Green on " + "+".join(green))
    else:
        reasons.append("No green continuity")

    scored: list[ScoredSetup] = []
    for tf in ("M", "W", "D"):
        st = states.get(tf)
        if not st:
            continue
        for setup in st.setups:
            pts = SETUP_POINTS.get(setup.kind, {}).get(tf, 0.0)
            scored.append(ScoredSetup(tf, setup, pts))

    setup_total = 0.0
    if scored:
        ordered = sorted(scored, key=lambda s: s.points, reverse=True)
        setup_total = ordered[0].points + 0.25 * sum(s.points for s in ordered[1:])
    total += min(MAX_SETUP_POINTS, setup_total)

    primary = _pick_primary(scored, price)
    dist = None
    if primary:
        dist = trigger_distance_pct(price, primary.setup.trigger)
        total += proximity_points(dist, primary.setup.triggered)
        reasons.append(_describe(primary, dist))
        for other in sorted(scored, key=lambda s: s.points, reverse=True):
            if other is not primary:
                reasons.append(f"{TF_NAMES[other.tf]} {other.setup.label}")

    total += liquidity_points(avg_dollar_volume)
    if atr_pct is not None and atr_pct < MIN_ATR_PCT:
        total *= PINNED_PENALTY
        reasons.append(f"Very low volatility (avg range {atr_pct:.2f}%), possibly pinned by a deal")
    return Score(
        score=round(min(100.0, total), 1),
        primary=primary,
        setups=scored,
        reasons=reasons,
        full_continuity=full,
        mw_green=mw_green,
        trigger_distance_pct=None if dist is None else round(dist, 2),
    )


def _pick_primary(scored: list[ScoredSetup], price: float) -> Optional[ScoredSetup]:
    """Prefer an untriggered setup whose trigger is above price, weighted by closeness."""
    if not scored:
        return None

    def rank(s: ScoredSetup) -> float:
        dist = trigger_distance_pct(price, s.setup.trigger)
        return s.points + proximity_points(dist, s.setup.triggered) + (5.0 if not s.setup.triggered else 0.0)

    return max(scored, key=rank)


def _describe(s: ScoredSetup, dist: float) -> str:
    tf = TF_NAMES[s.tf]
    if s.setup.triggered or dist <= 0:
        return f"{tf} {s.setup.label} — triggered above {s.setup.trigger:.2f}"
    return f"{tf} {s.setup.label} — trigger {s.setup.trigger:.2f} ({dist:+.1f}% away)"
