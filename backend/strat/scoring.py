"""Actionability score for long Strat setups (0-100, higher is better)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional

from .candles import TWO_UP, Setup, TimeframeState

TF_NAMES = {"M": "Monthly", "W": "Weekly", "D": "Daily"}

# Only weekly setups are ranked; Monthly and Daily candles are context (continuity, Monthly 2U).
SETUP_TF = "W"

CONTINUITY_POINTS = {"M": 12.0, "W": 12.0, "D": 6.0}
FULL_CONTINUITY_BONUS = 8.0
MONTHLY_2U_POINTS = 20.0

# Pending (not yet triggered) weekly setups are the most actionable.
SETUP_POINTS = {
    "2-1-2-pending": 23.0,
    "3-1-2-pending": 23.0,
    "inside": 20.0,
    "hammer": 18.0,
    "2-1-2": 12.0,
    "3-1-2": 12.0,
    "1-2-2": 10.0,
    "2D-2U": 9.0,
    "hammer-triggered": 8.0,
}
MAX_SETUP_POINTS = 25.0
PROXIMITY_POINTS = 15.0
PROXIMITY_WINDOW_PCT = 5.0
LIQUIDITY_POINTS = 10.0
# Names whose average daily range is this tight are usually pinned by a pending deal.
MIN_ATR_PCT = 0.5
PINNED_PENALTY = 0.5

MAX_RAW_POINTS = (
    MONTHLY_2U_POINTS
    + sum(CONTINUITY_POINTS.values())
    + FULL_CONTINUITY_BONUS
    + MAX_SETUP_POINTS
    + PROXIMITY_POINTS
    + LIQUIDITY_POINTS
)


@dataclass
class ScoredSetup:
    tf: str
    setup: Setup
    points: float


@dataclass
class Component:
    key: str
    label: str
    points: float
    max_points: float
    detail: str


@dataclass
class Score:
    score: float
    raw: float
    breakdown: list[Component]
    primary: Optional[ScoredSetup]
    setups: list[ScoredSetup]
    reasons: list[str]
    full_continuity: bool
    mw_green: bool
    monthly_2u: bool
    trigger_distance_pct: Optional[float]

    @property
    def has_setup(self) -> bool:
        return bool(self.setups)


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
    parts: list[Component] = []

    weekly = states.get(SETUP_TF)
    scored = [
        ScoredSetup(SETUP_TF, setup, SETUP_POINTS.get(setup.kind, 0.0))
        for setup in (weekly.setups if weekly else [])
    ]
    ordered = sorted(scored, key=lambda s: s.points, reverse=True)
    primary = _pick_primary(scored, price)

    monthly = states.get("M")
    monthly_2u = bool(monthly and monthly.strat == TWO_UP)
    parts.append(
        Component(
            "monthly_2u", "Monthly 2U", MONTHLY_2U_POINTS if monthly_2u else 0.0, MONTHLY_2U_POINTS,
            "current month is 2U" if monthly_2u else f"current month is {monthly.strat if monthly else 'n/a'}",
        )
    )

    colors = {tf: (s.color if s else None) for tf, s in states.items()}
    green = [tf for tf in ("M", "W", "D") if colors.get(tf) == "green"]
    full = len(green) == 3
    mw_green = "M" in green and "W" in green
    cont = sum(CONTINUITY_POINTS[tf] for tf in green) + (FULL_CONTINUITY_BONUS if full else 0.0)
    cont_detail = " ".join(f"{tf} +{CONTINUITY_POINTS[tf]:g}" for tf in green) or "no timeframe green"
    if full:
        cont_detail += f", full M+W+D bonus +{FULL_CONTINUITY_BONUS:g}"
    parts.append(
        Component(
            "continuity", "Continuity (green vs open)", cont,
            sum(CONTINUITY_POINTS.values()) + FULL_CONTINUITY_BONUS, cont_detail,
        )
    )

    setup_pts = 0.0
    setup_detail = "no weekly setup"
    if ordered:
        extra = 0.25 * sum(s.points for s in ordered[1:])
        setup_pts = min(MAX_SETUP_POINTS, ordered[0].points + extra)
        setup_detail = f"{ordered[0].setup.label} {ordered[0].points:g}"
        if extra:
            setup_detail += f" + 25% of other weekly setups {extra:g}"
        if ordered[0].points + extra > MAX_SETUP_POINTS:
            setup_detail += f", capped at {MAX_SETUP_POINTS:g}"
    parts.append(Component("weekly_setup", "Weekly setup", setup_pts, MAX_SETUP_POINTS, setup_detail))

    dist = None
    prox = 0.0
    prox_detail = "no trigger"
    if primary:
        dist = trigger_distance_pct(price, primary.setup.trigger)
        prox = proximity_points(dist, primary.setup.triggered)
        prox_detail = (
            "already triggered (half credit)"
            if primary.setup.triggered or dist <= 0
            else f"{dist:.2f}% below trigger (full credit at 0%, none at {PROXIMITY_WINDOW_PCT:g}%)"
        )
    parts.append(Component("proximity", "Distance to trigger", prox, PROXIMITY_POINTS, prox_detail))

    liq = liquidity_points(avg_dollar_volume)
    parts.append(
        Component(
            "liquidity", "Liquidity", liq, LIQUIDITY_POINTS,
            f"avg ${avg_dollar_volume / 1e6:,.0f}M/day (log scale, 0 at $50M, max at $5B)",
        )
    )

    raw = sum(c.points for c in parts)
    if atr_pct is not None and atr_pct < MIN_ATR_PCT:
        penalty = -raw * (1 - PINNED_PENALTY)
        parts.append(
            Component("pinned", "Pinned penalty", penalty, 0.0, f"avg daily range {atr_pct:.2f}% < {MIN_ATR_PCT}%, score halved")
        )
        raw += penalty

    if primary:
        reasons.append(_describe(primary, dist))
        reasons.extend(f"Weekly {s.setup.label}" for s in ordered if s is not primary)
    else:
        reasons.append("No weekly setup")
    if monthly_2u:
        reasons.append("Monthly 2U")
    if full:
        reasons.append("Full continuity M+W+D green")
    elif mw_green:
        reasons.append("M+W green")
    elif green:
        reasons.append("Green on " + "+".join(green))
    else:
        reasons.append("No green continuity")
    if atr_pct is not None and atr_pct < MIN_ATR_PCT:
        reasons.append(f"Very low volatility (avg range {atr_pct:.2f}%), possibly pinned by a deal")

    return Score(
        score=round(min(100.0, raw * 100.0 / MAX_RAW_POINTS), 1),
        raw=round(raw, 2),
        breakdown=parts,
        primary=primary,
        setups=scored,
        reasons=reasons,
        full_continuity=full,
        mw_green=mw_green,
        monthly_2u=monthly_2u,
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
