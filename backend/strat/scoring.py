"""Leadership-first score for the Stock Scanner (0-100, higher is better).

Leadership comes first: relative strength of the 1M/3M/6M returns (against the peer group and against QQQ),
theme strength and trend (price above a rising 10- and 20-day average) are 80% of the points. The weekly Strat setup is a timing overlay worth at most
10 points. It is never a gate, and a name with no setup still scores on its leadership. A leader that is losing its
trend (lost moving averages, a deep drawdown from the high, 1M momentum turning negative) is demoted by a breakdown penalty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .candles import TWO_UP, TimeframeState
from .leadership import (
    BROKEN,
    FULL_EXCESS_PCT,
    WARNING,
    Breakdown,
    Trend,
    leader_status,
    LAGGARD,
)
from .legacy_scoring import (
    MAX_SETUP_POINTS,
    MIN_ATR_PCT,
    PINNED_PENALTY,
    PROXIMITY_POINTS as LEGACY_PROXIMITY_POINTS,
    SETUP_POINTS,
    SETUP_TF,
    TF_NAMES,
    Component,
    ScoredSetup,
    ThemeStrength,
    _describe,
    _pick_primary,
    liquidity_points,
    proximity_points as legacy_proximity_points,
    trigger_distance_pct,
)
from .pricebehavior import (
    CONTRACTION_RANGE,
    CONTRACTION_WEIGHT,
    KILL_LOOKBACK,
    KILL_PENALTY,
    RELATIVE_RANGE,
    RELATIVE_WEIGHT,
    KillCandle,
    Tightness,
    tightness_fraction,
)
from .perf import MOMENTUM_WEIGHTS, PERIOD_LABELS, PERIODS, Momentum

__all__ = ["ThemeStrength", "Score", "score_symbol", "trigger_distance_pct", "liquidity_points", "max_raw_points"]

# Leadership is 80 of 100 (RS 15, Vs QQQ 30, theme 25, trend 10), plus 5 for range tightness and 5 for liquidity.
# Vs QQQ stays the largest single factor. Theme was raised from 10 to 25, and Vs QQQ cut from 45 to 30, so a stock
# that leads its theme is not capped by a middling QQQ comparison. The earlier 45/10 split came from the rank-quality
# backtest (README): outperformance over QQQ ranks big winners better than a percentile, which saturates at P99.
RS_POINTS = 15.0  # blended 1M/3M/6M return percentile within the peer group
QQQ_POINTS = 30.0  # outperformance over QQQ
THEME_POINTS = 25.0  # rank of the stock's primary theme on the Themes page
TREND_POINTS = 10.0  # price above a rising 10-day and a rising 20-day average
TIGHTNESS_POINTS = 5.0  # calm, contracting daily ranges
LIQUIDITY_POINTS = 5.0

# Strat timing overlay (10 of 100)
SETUP_OVERLAY_POINTS = 4.0
PROXIMITY_OVERLAY_POINTS = 2.5
CONTINUITY_POINTS = {"M": 0.75, "W": 0.75, "D": 0.25}
FULL_CONTINUITY_BONUS = 0.25
MONTHLY_2U_POINTS = 1.5
CONTINUITY_MAX = sum(CONTINUITY_POINTS.values()) + FULL_CONTINUITY_BONUS
STRAT_OVERLAY_MAX = SETUP_OVERLAY_POINTS + PROXIMITY_OVERLAY_POINTS + CONTINUITY_MAX + MONTHLY_2U_POINTS

TREND_PERIODS = (10, 20)  # only these averages score; the 50-day and the highs only feed the breakdown rules
TREND_ABOVE_POINTS = 3.0  # per average the price is above
TREND_RISING_POINTS = 2.0  # per average that is rising (above its value 5 bars ago)
TREND_PER_MA_POINTS = TREND_ABOVE_POINTS + TREND_RISING_POINTS
TREND_SUB_WEIGHTS = [
    f"10-day {TREND_PER_MA_POINTS:g} pts · 20-day {TREND_PER_MA_POINTS:g} pts",
    f"each: price above {TREND_ABOVE_POINTS:g} + average rising {TREND_RISING_POINTS:g}",
]
CONTINUITY_SUB_WEIGHTS = [
    "Monthly " + f"{CONTINUITY_POINTS['M']:g}", "Weekly " + f"{CONTINUITY_POINTS['W']:g}",
    "Daily " + f"{CONTINUITY_POINTS['D']:g}", f"all three +{FULL_CONTINUITY_BONUS:g}",
]

# Breakdown: share of the score that is kept.
BROKEN_FACTOR = 0.5
WARNING_FACTOR = 0.9

# ETFs belong to no theme and themes are not traded, so they are scored without those components on a smaller scale.
STOCK_MAX_RAW_POINTS = (
    RS_POINTS + QQQ_POINTS + THEME_POINTS + TREND_POINTS + TIGHTNESS_POINTS + STRAT_OVERLAY_MAX + LIQUIDITY_POINTS
)
ETF_MAX_RAW_POINTS = STOCK_MAX_RAW_POINTS - THEME_POINTS
THEME_MAX_RAW_POINTS = ETF_MAX_RAW_POINTS - LIQUIDITY_POINTS
MAX_RAW_POINTS = STOCK_MAX_RAW_POINTS


def max_raw_points(kind: str) -> float:
    return {"etf": ETF_MAX_RAW_POINTS, "theme": THEME_MAX_RAW_POINTS}.get(kind, STOCK_MAX_RAW_POINTS)


@dataclass
class Score:
    score: float
    raw: float
    max_raw: float
    breakdown: list[Component]
    primary: Optional[ScoredSetup]
    setups: list[ScoredSetup]
    reasons: list[str]
    full_continuity: bool
    mw_green: bool
    monthly_2u: bool
    trigger_distance_pct: Optional[float]
    rs: Optional[float] = None  # blended 1M/3M/6M percentile, 0..1
    status: str = LAGGARD  # "leader" | "broken" | "laggard"
    trend_break: Breakdown = field(default_factory=lambda: Breakdown("none"))

    @property
    def has_setup(self) -> bool:
        return bool(self.setups)

    @property
    def is_leader(self) -> bool:
        return self.status == "leader"


def theme_strength_points(strength: Optional[ThemeStrength]) -> float:
    """Up to THEME_POINTS by the theme's rank among all themes: the top theme gets all of them."""
    if strength is None or strength.total <= 0:
        return 0.0
    return THEME_POINTS * (strength.total - strength.rank + 1) / strength.total


def relative_strength_points(momentum: Optional[Momentum]) -> float:
    if momentum is None or momentum.blended is None:
        return 0.0
    return RS_POINTS * min(1.0, max(0.0, momentum.blended))


def qqq_points(excess: Optional[Mapping[str, Optional[float]]]) -> float:
    """Weighted credit for beating QQQ: full at +15 / +40 / +70 points over 1M / 3M / 6M."""
    if not excess:
        return 0.0
    have = {p: excess.get(p) for p in PERIODS if excess.get(p) is not None}
    total = sum(MOMENTUM_WEIGHTS[p] for p in have)
    if not total:
        return 0.0
    frac = sum(MOMENTUM_WEIGHTS[p] * min(1.0, max(0.0, v / FULL_EXCESS_PCT[p])) for p, v in have.items()) / total
    return QQQ_POINTS * frac


def trend_points(trend: Optional[Trend]) -> float:
    """Price above a rising 10-day and a rising 20-day average: 4 for being above plus 2.5 for rising, each."""
    if trend is None:
        return 0.0
    return sum(
        (TREND_ABOVE_POINTS if trend.above(p) else 0.0) + (TREND_RISING_POINTS if trend.rising.get(p) else 0.0)
        for p in TREND_PERIODS
    )


def score_symbol(
    states: Mapping[str, Optional[TimeframeState]],
    price: float,
    avg_dollar_volume: float,
    atr_pct: Optional[float] = None,
    kind: str = "stock",
    theme: Optional[ThemeStrength] = None,
    momentum: Optional[Momentum] = None,
    theme_name: str = "",
    trend: Optional[Trend] = None,
    excess: Optional[Mapping[str, Optional[float]]] = None,
    trend_break: Optional[Breakdown] = None,
    tightness: Optional[Tightness] = None,
    kill: Optional[KillCandle] = None,
) -> Score:
    """Score one symbol.

    ``momentum`` holds its 1M/3M/6M returns and their percentile ranks within the peer group; ``excess`` is each
    return minus QQQ; ``trend`` the moving-average and high structure; ``trend_break`` whether the
    leader is losing that trend. Stocks also get Theme strength from their primary theme (``theme``).
    """
    trend_break = trend_break or Breakdown("none")
    parts: list[Component] = []

    parts.append(_rs_component(momentum))
    parts.append(_qqq_component(excess))
    if kind == "stock":
        parts.append(_theme_component(theme, theme_name))
    parts.append(_trend_component(trend))
    parts.append(_tightness_component(tightness))

    weekly = states.get(SETUP_TF)
    scored = [
        ScoredSetup(SETUP_TF, setup, SETUP_POINTS.get(setup.kind, 0.0)) for setup in (weekly.setups if weekly else [])
    ]
    ordered = sorted(scored, key=lambda s: s.points, reverse=True)
    primary = _pick_primary(scored, price)

    setup_raw = 0.0
    setup_detail = "no weekly setup (not required: a leader still scores on leadership)"
    if ordered:
        extra = 0.25 * sum(s.points for s in ordered[1:])
        setup_raw = min(MAX_SETUP_POINTS, ordered[0].points + extra)
        setup_detail = f"{ordered[0].setup.label}: {setup_raw:g}/{MAX_SETUP_POINTS:g} setup quality"
    parts.append(
        Component(
            "weekly_setup", "Strat timing · weekly setup", SETUP_OVERLAY_POINTS * setup_raw / MAX_SETUP_POINTS,
            SETUP_OVERLAY_POINTS, setup_detail,
        )
    )

    dist = None
    prox = 0.0
    prox_detail = "no trigger"
    if primary:
        dist = trigger_distance_pct(price, primary.setup.trigger)
        prox = PROXIMITY_OVERLAY_POINTS * legacy_proximity_points(dist, primary.setup.triggered) / LEGACY_PROXIMITY_POINTS
        prox_detail = (
            "already triggered (half credit)"
            if primary.setup.triggered or dist <= 0
            else f"{dist:.2f}% below trigger (full credit at 0%, none at 5%)"
        )
    parts.append(Component("proximity", "Strat timing · distance to trigger", prox, PROXIMITY_OVERLAY_POINTS, prox_detail))

    colors = {tf: (s.color if s else None) for tf, s in states.items()}
    green = [tf for tf in ("M", "W", "D") if colors.get(tf) == "green"]
    full = len(green) == 3
    mw_green = "M" in green and "W" in green
    cont = sum(CONTINUITY_POINTS[tf] for tf in green) + (FULL_CONTINUITY_BONUS if full else 0.0)
    cont_detail = " ".join(f"{tf} +{CONTINUITY_POINTS[tf]:g}" for tf in green) or "no timeframe green"
    if full:
        cont_detail += f", full M+W+D bonus +{FULL_CONTINUITY_BONUS:g}"
    parts.append(
        Component("continuity", "Strat timing · continuity", cont, CONTINUITY_MAX, cont_detail, sub_weights=CONTINUITY_SUB_WEIGHTS)
    )

    monthly = states.get("M")
    monthly_2u = bool(monthly and monthly.strat == TWO_UP)
    parts.append(
        Component(
            "monthly_2u", "Strat timing · Monthly 2U", MONTHLY_2U_POINTS if monthly_2u else 0.0, MONTHLY_2U_POINTS,
            "completed month is 2U" if monthly_2u else f"completed month is {monthly.strat if monthly else 'n/a'}",
        )
    )

    if kind != "theme":
        liq = liquidity_points(avg_dollar_volume) * LIQUIDITY_POINTS / 10.0
        parts.append(
            Component(
                "liquidity", "Liquidity", liq, LIQUIDITY_POINTS,
                f"avg ${avg_dollar_volume / 1e6:,.0f}M/day (log scale, 0 at $50M, max at $5B)",
            )
        )

    max_raw = max_raw_points(kind)
    for c in parts:
        c.weight_pct = round(c.max_points / max_raw * 100.0, 1)

    raw = sum(c.points for c in parts)
    if trend_break.level in (BROKEN, WARNING):
        keep = BROKEN_FACTOR if trend_break.level == BROKEN else WARNING_FACTOR
        label = "Breakdown penalty" if trend_break.level == BROKEN else "Weakening penalty"
        detail = "; ".join(trend_break.reasons) + f" — score × {keep:g}"
        parts.append(Component("breakdown", label, -raw * (1 - keep), 0.0, detail))
        raw *= keep
    if kill is not None and kill.penalty > 0:
        parts.append(_kill_component(kill, raw))
        raw *= 1 - kill.penalty
    if atr_pct is not None and atr_pct < MIN_ATR_PCT:
        penalty = -raw * (1 - PINNED_PENALTY)
        parts.append(
            Component("pinned", "Pinned penalty", penalty, 0.0, f"avg daily range {atr_pct:.2f}% < {MIN_ATR_PCT}%, score halved")
        )
        raw += penalty

    reasons: list[str] = []
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
    if kill is not None and kill.penalty > 0:
        reasons.append(f"Kill candle {kill.date} (score -{kill.penalty * 100:.0f}%)")
    if trend_break.level != "none":
        reasons.append(("Broken: " if trend_break.level == BROKEN else "Weakening: ") + "; ".join(trend_break.reasons))
    if atr_pct is not None and atr_pct < MIN_ATR_PCT:
        reasons.append(f"Very low volatility (avg range {atr_pct:.2f}%), possibly pinned by a deal")

    rs = momentum.blended if momentum else None
    return Score(
        score=round(max(0.0, min(100.0, raw * 100.0 / max_raw)), 1),
        raw=round(raw, 2),
        max_raw=round(max_raw, 2),
        breakdown=parts,
        primary=primary,
        setups=scored,
        reasons=reasons,
        full_continuity=full,
        mw_green=mw_green,
        monthly_2u=monthly_2u,
        trigger_distance_pct=None if dist is None else round(dist, 2),
        rs=rs,
        status=leader_status(rs, trend_break),
        trend_break=trend_break,
    )


def _peer_label(momentum: Momentum) -> str:
    return {"stock": "stocks", "etf": "ETFs", "theme": "themes"}.get(momentum.group, "peers")


def _rs_sub_weights() -> list[str]:
    return [f"{PERIOD_LABELS[p]} {MOMENTUM_WEIGHTS[p] * 100:.0f}%" for p in PERIODS]


def _rs_component(momentum: Optional[Momentum]) -> Component:
    if momentum is None or momentum.blended is None:
        return Component(
            "rs", "Relative strength", 0.0, RS_POINTS, "not enough price history for a 1M/3M/6M return",
            sub_weights=_rs_sub_weights(),
        )
    parts = []
    for p in PERIODS:
        ret, pct = momentum.returns[p], momentum.percentiles[p]
        parts.append(
            f"{PERIOD_LABELS[p]} n/a" if ret is None or pct is None else f"{PERIOD_LABELS[p]} {ret:+.1f}% (P{pct * 100:.0f})"
        )
    weights = "/".join(f"{MOMENTUM_WEIGHTS[p] * 100:.0f}" for p in PERIODS)
    n = max(momentum.peers.values(), default=0)
    detail = (
        f"{' · '.join(parts)}; percentile among {n} {_peer_label(momentum)}, weighted {weights} (1M/3M/6M) "
        f"= P{momentum.blended * 100:.0f}; {RS_POINTS:g} × {momentum.blended:.2f}"
    )
    return Component(
        "rs", f"Relative strength · P{momentum.blended * 100:.0f}", relative_strength_points(momentum), RS_POINTS, detail,
        sub_weights=_rs_sub_weights(),
    )


def _qqq_component(excess: Optional[Mapping[str, Optional[float]]]) -> Component:
    label = "Vs QQQ"
    subs = [
        f"{PERIOD_LABELS[p]} {MOMENTUM_WEIGHTS[p] * 100:.0f}% (full at +{FULL_EXCESS_PCT[p]:g} pts)" for p in PERIODS
    ]
    if not excess or all(excess.get(p) is None for p in PERIODS):
        return Component("qqq", label, 0.0, QQQ_POINTS, "no QQQ comparison available", sub_weights=subs)
    bits = [
        f"{PERIOD_LABELS[p]} {excess[p]:+.1f} pts (full at +{FULL_EXCESS_PCT[p]:g})"
        for p in PERIODS
        if excess.get(p) is not None
    ]
    return Component(
        "qqq", label, qqq_points(excess), QQQ_POINTS,
        "return minus QQQ: " + " · ".join(bits), sub_weights=subs,
    )


def _theme_component(theme: Optional[ThemeStrength], theme_name: str) -> Component:
    label = "Theme strength"
    if theme is None:
        detail = f"no Themes-page score for {theme_name} yet" if theme_name else "not in any theme"
        return Component("theme_strength", label, 0.0, THEME_POINTS, detail)
    rank = f"#{theme.rank} of {theme.total}"
    return Component(
        "theme_strength",
        f"{label} · {theme.name} ({rank})",
        theme_strength_points(theme),
        THEME_POINTS,
        f"{theme.name}: leadership score {theme.score:.1f}, {rank} themes; {THEME_POINTS:g} × ({theme.total} − {theme.rank} + 1) / {theme.total}",
    )


def _trend_component(trend: Optional[Trend]) -> Component:
    label = "Trend"
    if trend is None:
        return Component("trend", label, 0.0, TREND_POINTS, "not enough price history", sub_weights=TREND_SUB_WEIGHTS)
    bits = []
    for p in TREND_PERIODS:
        above = trend.above(p)
        if above is None:
            bits.append(f"{p}-day n/a")
        else:
            bits.append(f"{p}-day {'above' if above else 'below'}{' & rising' if trend.rising.get(p) else ''}")
    return Component("trend", label, trend_points(trend), TREND_POINTS, "; ".join(bits), sub_weights=TREND_SUB_WEIGHTS)


def _tightness_component(t: Optional[Tightness]) -> Component:
    label = "Range tightness"
    subs = [
        f"last-10 vs 50-day range {RELATIVE_WEIGHT * 100:.0f}% (full at ≤{RELATIVE_RANGE[0]:g}×, none at ≥{RELATIVE_RANGE[1]:g}×)",
        f"last-5 vs 20-day range {CONTRACTION_WEIGHT * 100:.0f}% (full at ≤{CONTRACTION_RANGE[0]:g}×, none at ≥{CONTRACTION_RANGE[1]:g}×)",
    ]
    if t is None:
        return Component("tightness", label, 0.0, TIGHTNESS_POINTS, "not enough price history", sub_weights=subs)
    detail = (
        f"10-day range {t.range10_pct:.1f}% of price vs 50-day {t.range50_pct:.1f}% ({t.ratio:.2f}×); "
        f"last 5 days {t.range5_pct:.1f}% vs 20-day {t.range20_pct:.1f}% ({t.contraction:.2f}×)"
    )
    return Component("tightness", label, TIGHTNESS_POINTS * tightness_fraction(t), TIGHTNESS_POINTS, detail, sub_weights=subs)


def _kill_component(kill: KillCandle, raw: float) -> Component:
    detail = (
        f"{kill.age} session{'s' if kill.age != 1 else ''} ago: range {kill.range_x_atr:.1f}× the 20-day ATR, volume "
        f"{kill.volume_x:.1f}× the 50-day average, closed {kill.close_position * 100:.0f}% up its range; "
        f"{KILL_PENALTY * 100:.0f}% penalty fading over {KILL_LOOKBACK} sessions = score × {1 - kill.penalty:.2f}"
    )
    return Component("kill_candle", f"Kill candle ({kill.date})", -raw * kill.penalty, 0.0, detail)
