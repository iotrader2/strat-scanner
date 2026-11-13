"""Setup-quality score for stocks and ETFs (0-100): built to rank the intraday trades most likely to reach a big R.

The previous score was leadership-first: 1M/3M/6M relative strength, with Vs QQQ given full credit only at fixed
+20 / +60 / +100 point excess returns (a threshold most names never reach). This score keeps leadership as context and
weights what the trade needs instead: a tight base (a small stop relative to normal volatility is the R-multiple
lever) and short-horizon relative strength.

Weights (stock, out of 100):

* **Tightness 30**: stop % / ATR(14) % 8*, ATR(5)/ATR(20) contraction 6, close tightness (+ inside day / NR7) 6,
  volume dry-up 3, trigger-day volume 2*, distance from the 10/21 EMA in ATRs 5.
* **Short RS 25**: intraday RS (open to the trigger bar, minus QQQ) 10*, 10-day and 20-day excess return vs QQQ as a
  percentile of the universe 5 + 5, RS line (stock / QQQ) at a 20-day high 3, +2 when it got there before price.
* **Setup 20**: trend (rising 10/20-day averages) 8, M/W/D continuity 7, liquidity 5.
* **Theme 15**: the rank of the stock's primary theme.
* **Long RS 10**: the blended 1M/3M/6M percentile (already a percentile, so no threshold).

Parts marked * only exist once a 15-minute alert fires (they need the trigger bar and the stop). The scanner ranks
on the other 80 points, rescaled to 0-100; :func:`entry_score` adds the entry parts and is frozen on the alert, so
every trade keeps the score it was taken with (raw inputs and points) for :mod:`strat.score_report`.

These weights are a starting point. Do not tune them on a handful of trades: let ~200 closed trades accumulate and use
``npm run score:report`` (Spearman of each part with R, hit rate of R >= 1.5 per score quintile).

ETFs have no theme (scan 65, entry 85). Themes are ranked with the leadership score in :mod:`strat.scoring`, which
also feeds the Theme points here.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

import pandas as pd

from .candles import TWO_UP, TimeframeState, continuity_color
from .ariel_setups import SETUP_POINTS, SETUP_TF
from .leadership import BROKEN, WARNING, Breakdown, Trend, leader_status
from .legacy_scoring import (
    MIN_ATR_PCT,
    PINNED_PENALTY,
    Component,
    ScoredSetup,
    ThemeStrength,
    _describe,
    _pick_primary,
    liquidity_points,
    trigger_distance_pct,
)
from .perf import MOMENTUM_WEIGHTS, PERIOD_LABELS, PERIODS, Momentum
from .pricebehavior import KillCandle
from . import scoring as leadership_scoring

# ---------------------------------------------------------------------------------------------------------- weights

# Tightness (30)
STOP_ATR_POINTS = 8.0  # entry only
ATR_CONTRACTION_POINTS = 6.0
CLOSE_TIGHTNESS_POINTS = 6.0  # 4 for the close spread + 2 for an inside day / NR7
CLOSE_SPREAD_POINTS = 4.0
NARROW_DAY_POINTS = 2.0
VOLUME_DRYUP_POINTS = 3.0
TRIGGER_VOLUME_POINTS = 2.0  # entry only
EMA_DISTANCE_POINTS = 5.0
# Short RS (25)
INTRADAY_RS_POINTS = 10.0  # entry only
RS_10D_POINTS = 5.0
RS_20D_POINTS = 5.0
RS_LINE_POINTS = 5.0  # 3 at a 20-day high + 2 when the RS line led price there
RS_LINE_HIGH_POINTS = 3.0
RS_LINE_LEAD_POINTS = 2.0
# Setup (20)
TREND_POINTS = 8.0
CONTINUITY_POINTS = 7.0
LIQUIDITY_POINTS = 5.0
# Theme (15) and long RS (10)
THEME_POINTS = 15.0
LONG_RS_POINTS = 10.0

GROUPS = {
    "tightness": ("stop_atr", "atr_contraction", "close_tightness", "volume_dryup", "trigger_volume", "ema_distance"),
    "short_rs": ("intraday_rs", "rs_10d", "rs_20d", "rs_line"),
    "setup": ("trend", "continuity", "liquidity"),
    "theme": ("theme_strength",),
    "long_rs": ("rs",),
}
GROUP_LABELS = {"tightness": "Tightness", "short_rs": "Short RS", "setup": "Setup", "theme": "Theme", "long_rs": "Long RS"}
ENTRY_KEYS = ("stop_atr", "trigger_volume", "intraday_rs")
ENTRY_MAX_POINTS = STOP_ATR_POINTS + TRIGGER_VOLUME_POINTS + INTRADAY_RS_POINTS

STOCK_SCAN_MAX = (
    ATR_CONTRACTION_POINTS + CLOSE_TIGHTNESS_POINTS + VOLUME_DRYUP_POINTS + EMA_DISTANCE_POINTS
    + RS_10D_POINTS + RS_20D_POINTS + RS_LINE_POINTS
    + TREND_POINTS + CONTINUITY_POINTS + LIQUIDITY_POINTS
    + THEME_POINTS + LONG_RS_POINTS
)
ETF_SCAN_MAX = STOCK_SCAN_MAX - THEME_POINTS
STOCK_ENTRY_MAX = STOCK_SCAN_MAX + ENTRY_MAX_POINTS
ETF_ENTRY_MAX = ETF_SCAN_MAX + ENTRY_MAX_POINTS

# ------------------------------------------------------------------------------------------------- full / no credit
# Each pair is (full credit, no credit); linear in between. Volatility-relative wherever possible, so a 3% ATR name
# and a 9% ATR name are judged on the same scale.
STOP_ATR_RANGE = (0.10, 0.35)  # stop % as a share of ATR(14) %
ATR_CONTRACTION_RANGE = (0.60, 1.00)  # ATR(5) / ATR(20); below ~0.7 is a real contraction
CLOSE_SPREAD_RANGE = (0.20, 0.75)  # stdev of the last 5 closes, % of price, as a share of ATR(14) %
VOLUME_DRYUP_RANGE = (0.60, 1.00)  # 5-day / 50-day average volume
TRIGGER_VOLUME_RANGE = (1.50, 1.00)  # today's volume to the trigger bar vs a pro-rated 20-day average
EMA_DISTANCE_RANGE = (0.50, 2.00)  # ATRs from the nearer of the 10 / 21-day EMA
INTRADAY_RS_RANGE = (0.50, 0.0)  # (stock - QQQ) % since the open, in ATR(14) %; 0 or worse earns nothing

ATR_PERIOD = 14
ATR_SHORT, ATR_LONG = 5, 20
CLOSE_BARS = 5
NR_BARS = 7
DRYUP_BARS, VOLUME_BASE_BARS = 5, 50
EMA_PERIODS = (10, 21)
SHORT_RS_PERIODS = (10, 20)
RS_LINE_BARS = 20
MIN_BARS = VOLUME_BASE_BARS + DRYUP_BARS + 1
SESSION_BARS_15M = 26


def frac(value: Optional[float], full: float, none: float) -> float:
    """1 at ``full`` (or better), 0 at ``none`` (or worse), linear in between; works in either direction."""
    if value is None or not math.isfinite(value) or full == none:
        return 0.0
    return min(1.0, max(0.0, (none - value) / (none - full)))


# ------------------------------------------------------------------------------------------------------- the inputs


@dataclass(frozen=True)
class BaseMetrics:
    """Tightness of the base, from completed daily bars only (today's bar in progress is left out)."""

    atr14_pct: float  # ATR(14) as % of the last close
    atr_ratio: float  # ATR(5) / ATR(20)
    close_std_pct: float  # stdev of the last 5 closes, % of the last close
    inside_day: bool
    nr7: bool  # the last bar has the narrowest range of the last 7
    volume_dryup: Optional[float]  # 5-day / 50-day average volume
    ema_dist_atr: Optional[float]  # |close - nearer of EMA10 / EMA21| in ATR(14)
    ema10_dist_atr: Optional[float]  # signed: + above the average
    ema21_dist_atr: Optional[float]

    @property
    def close_spread_x_atr(self) -> Optional[float]:
        return self.close_std_pct / self.atr14_pct if self.atr14_pct > 0 else None


@dataclass(frozen=True)
class ShortRS:
    """10 / 20-day excess return over QQQ (percentage points), their universe percentiles, and the RS line."""

    excess_10d: Optional[float]
    excess_20d: Optional[float]
    pct_10d: Optional[float] = None  # 0..1 within the peer group (filled by the scan)
    pct_20d: Optional[float] = None
    rs_line_high: bool = False  # stock / QQQ closed at a 20-day high on the last bar
    price_high: bool = False  # the close itself is at a 20-day closing high


def _true_range(daily: pd.DataFrame) -> pd.Series:
    prev = daily.close.shift(1)
    return pd.concat([daily.high, prev], axis=1).max(axis=1) - pd.concat([daily.low, prev], axis=1).min(axis=1)


def base_metrics(daily: Optional[pd.DataFrame]) -> Optional[BaseMetrics]:
    """Base tightness of completed daily bars; None with fewer than ``MIN_BARS`` bars."""
    if daily is None or len(daily) < MIN_BARS:
        return None
    close = daily.close.astype(float)
    price = float(close.iloc[-1])
    if not price > 0:
        return None
    tr = _true_range(daily).iloc[1:]
    atr14 = float(tr.tail(ATR_PERIOD).mean())
    atr5, atr20 = float(tr.tail(ATR_SHORT).mean()), float(tr.tail(ATR_LONG).mean())
    span = (daily.high - daily.low).astype(float)
    last, prev = daily.iloc[-1], daily.iloc[-2]
    inside = bool(last.high <= prev.high and last.low >= prev.low)
    nr7 = bool(span.iloc[-1] <= span.tail(NR_BARS).min())
    vol = daily.volume.astype(float)
    recent = float(vol.tail(DRYUP_BARS).mean())
    base = float(vol.iloc[-(DRYUP_BARS + VOLUME_BASE_BARS) : -DRYUP_BARS].mean())
    dryup = recent / base if base > 0 else None
    dists = {}
    for p in EMA_PERIODS:
        ema = float(close.ewm(span=p, adjust=False).mean().iloc[-1])
        dists[p] = (price - ema) / atr14 if atr14 > 0 else None
    near = [abs(v) for v in dists.values() if v is not None]
    return BaseMetrics(
        atr14_pct=atr14 / price * 100.0,
        atr_ratio=atr5 / atr20 if atr20 > 0 else 1.0,
        close_std_pct=float(close.tail(CLOSE_BARS).std(ddof=0)) / price * 100.0,
        inside_day=inside,
        nr7=nr7,
        volume_dryup=dryup,
        ema_dist_atr=min(near) if near else None,
        ema10_dist_atr=dists[10],
        ema21_dist_atr=dists[21],
    )


def _ret(close: pd.Series, bars: int) -> Optional[float]:
    if len(close) <= bars:
        return None
    base = float(close.iloc[-bars - 1])
    return (float(close.iloc[-1]) / base - 1.0) * 100.0 if base > 0 else None


def short_rs(daily: Optional[pd.DataFrame], benchmark: Optional[pd.Series]) -> ShortRS:
    """10 / 20-day excess over the benchmark and the 20-day RS-line high, on completed daily bars.

    The benchmark is aligned to the stock's dates (a missing QQQ leaves everything empty and false).
    """
    if daily is None or daily.empty or benchmark is None or benchmark.empty:
        return ShortRS(None, None)
    close = daily.close.astype(float)
    bench = benchmark.astype(float).reindex(close.index).ffill()
    out: dict[str, Optional[float]] = {}
    for n in SHORT_RS_PERIODS:
        mine, theirs = _ret(close, n), _ret(bench.dropna(), n) if bench.notna().sum() > n else None
        out[f"excess_{n}d"] = None if mine is None or theirs is None else mine - theirs
    line_high = price_high = False
    if len(close) >= RS_LINE_BARS:
        ratio = (close / bench).tail(RS_LINE_BARS)
        if ratio.notna().all() and (bench.tail(RS_LINE_BARS) > 0).all():
            line_high = bool(ratio.iloc[-1] >= ratio.max())
        price_high = bool(close.iloc[-1] >= close.tail(RS_LINE_BARS).max())
    return ShortRS(out["excess_10d"], out["excess_20d"], rs_line_high=line_high, price_high=price_high)


# --------------------------------------------------------------------------------------------------------- the score


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
    rs: Optional[float] = None
    status: str = "laggard"
    trend_break: Breakdown = None  # type: ignore[assignment]
    keep: float = 1.0  # share of the points kept after the breakdown / kill / pinned penalties
    inputs: Optional[dict] = None  # the raw inputs, for the alert snapshot

    @property
    def has_setup(self) -> bool:
        return bool(self.setups)

    @property
    def is_leader(self) -> bool:
        return self.status == "leader"


def max_scan_points(kind: str) -> float:
    return ETF_SCAN_MAX if kind == "etf" else STOCK_SCAN_MAX


def max_entry_points(kind: str) -> float:
    return ETF_ENTRY_MAX if kind == "etf" else STOCK_ENTRY_MAX


def _c(key: str, label: str, points: float, max_points: float, detail: str, subs: Sequence[str] = ()) -> Component:
    return Component(key, label, points, max_points, detail, sub_weights=list(subs))


def _fmt(v: Optional[float], spec: str = ".2f", suffix: str = "") -> str:
    return "n/a" if v is None else f"{v:{spec}}{suffix}"


def tightness_components(base: Optional[BaseMetrics]) -> list[Component]:
    if base is None:
        missing = "not enough price history"
        return [
            _c("atr_contraction", "ATR contraction", 0.0, ATR_CONTRACTION_POINTS, missing),
            _c("close_tightness", "Close tightness", 0.0, CLOSE_TIGHTNESS_POINTS, missing),
            _c("volume_dryup", "Volume dry-up", 0.0, VOLUME_DRYUP_POINTS, missing),
            _c("ema_distance", "Near the 10/21 EMA", 0.0, EMA_DISTANCE_POINTS, missing),
        ]
    spread = base.close_spread_x_atr
    narrow = base.inside_day or base.nr7
    close_pts = CLOSE_SPREAD_POINTS * frac(spread, *CLOSE_SPREAD_RANGE) + (NARROW_DAY_POINTS if narrow else 0.0)
    tags = [t for t, on in (("inside day", base.inside_day), ("NR7", base.nr7)) if on]
    return [
        _c(
            "atr_contraction", f"ATR contraction · {base.atr_ratio:.2f}×",
            ATR_CONTRACTION_POINTS * frac(base.atr_ratio, *ATR_CONTRACTION_RANGE), ATR_CONTRACTION_POINTS,
            f"ATR(5) / ATR(20) = {base.atr_ratio:.2f} (full at ≤{ATR_CONTRACTION_RANGE[0]:g}, none at ≥{ATR_CONTRACTION_RANGE[1]:g})",
        ),
        _c(
            "close_tightness", "Close tightness" + (f" · {' + '.join(tags)}" if tags else ""),
            close_pts, CLOSE_TIGHTNESS_POINTS,
            f"stdev of the last {CLOSE_BARS} closes {base.close_std_pct:.2f}% of price = {_fmt(spread)}× ATR(14) "
            f"(full at ≤{CLOSE_SPREAD_RANGE[0]:g}×, none at ≥{CLOSE_SPREAD_RANGE[1]:g}×)"
            + (f"; {' + '.join(tags)} +{NARROW_DAY_POINTS:g}" if tags else "; no inside day / NR7"),
            [f"close spread {CLOSE_SPREAD_POINTS:g}", f"inside day or NR7 {NARROW_DAY_POINTS:g}"],
        ),
        _c(
            "volume_dryup", f"Volume dry-up · {_fmt(base.volume_dryup)}×",
            VOLUME_DRYUP_POINTS * frac(base.volume_dryup, *VOLUME_DRYUP_RANGE), VOLUME_DRYUP_POINTS,
            f"{DRYUP_BARS}-day / {VOLUME_BASE_BARS}-day average volume = {_fmt(base.volume_dryup)} "
            f"(full at ≤{VOLUME_DRYUP_RANGE[0]:g}, none at ≥{VOLUME_DRYUP_RANGE[1]:g})",
        ),
        _c(
            "ema_distance", f"Near the 10/21 EMA · {_fmt(base.ema_dist_atr, '.1f')} ATR",
            EMA_DISTANCE_POINTS * frac(base.ema_dist_atr, *EMA_DISTANCE_RANGE), EMA_DISTANCE_POINTS,
            f"close vs EMA10 {_fmt(base.ema10_dist_atr, '+.2f')} ATR, vs EMA21 {_fmt(base.ema21_dist_atr, '+.2f')} ATR; "
            f"nearer {_fmt(base.ema_dist_atr)} (full at ≤{EMA_DISTANCE_RANGE[0]:g}, none at ≥{EMA_DISTANCE_RANGE[1]:g})",
        ),
    ]


def short_rs_components(srs: Optional[ShortRS], peers: int = 0) -> list[Component]:
    srs = srs or ShortRS(None, None)
    among = f" among {peers}" if peers else ""
    parts = []
    for n, pts, pct, ex in (
        (10, RS_10D_POINTS, srs.pct_10d, srs.excess_10d), (20, RS_20D_POINTS, srs.pct_20d, srs.excess_20d)
    ):
        label = f"{n}-day RS" + (f" · P{pct * 100:.0f}" if pct is not None else "")
        detail = (
            "no QQQ comparison available" if ex is None
            else f"{n}-day return minus QQQ {ex:+.1f} pts, percentile{among} = {_fmt(pct)}; {pts:g} × percentile"
        )
        parts.append(_c(f"rs_{n}d", label, pts * (pct or 0.0), pts, detail))
    lead = srs.rs_line_high and not srs.price_high
    line_pts = (RS_LINE_HIGH_POINTS if srs.rs_line_high else 0.0) + (RS_LINE_LEAD_POINTS if lead else 0.0)
    if not srs.rs_line_high:
        detail = f"stock / QQQ is not at a {RS_LINE_BARS}-day high"
    elif lead:
        detail = f"stock / QQQ at a {RS_LINE_BARS}-day high before price (+{RS_LINE_HIGH_POINTS:g} +{RS_LINE_LEAD_POINTS:g})"
    else:
        detail = f"stock / QQQ at a {RS_LINE_BARS}-day high, with price (+{RS_LINE_HIGH_POINTS:g})"
    parts.append(_c(
        "rs_line", "RS line" + (" · leads price" if lead else " · 20-day high" if srs.rs_line_high else ""),
        line_pts, RS_LINE_POINTS, detail,
        [f"20-day high {RS_LINE_HIGH_POINTS:g}", f"before price {RS_LINE_LEAD_POINTS:g}"],
    ))
    return parts


def _scaled(c: Component, max_points: float) -> Component:
    """A leadership-score component on this score's scale (same fraction of its maximum)."""
    share = c.points / c.max_points if c.max_points else 0.0
    return _c(c.key, c.label, max_points * share, max_points, c.detail, c.sub_weights)


TREND_ABOVE_POINTS, TREND_RISING_POINTS = 2.5, 1.5  # per average (10 and 20-day): 4 each, 8 in all
TF_GREEN_POINTS = {"M": 3.0, "W": 3.0, "D": 0.5}
FULL_GREEN_BONUS = 0.5


def trend_points(trend: Optional[Trend]) -> float:
    if trend is None:
        return 0.0
    return sum(
        (TREND_ABOVE_POINTS if trend.above(p) else 0.0) + (TREND_RISING_POINTS if trend.rising.get(p) else 0.0)
        for p in leadership_scoring.TREND_PERIODS
    )


def _trend_component(trend: Optional[Trend]) -> Component:
    c = leadership_scoring._trend_component(trend)
    per = TREND_ABOVE_POINTS + TREND_RISING_POINTS
    return _c(
        "trend", "Trend", trend_points(trend), TREND_POINTS, c.detail,
        [f"10-day {per:g} pts · 20-day {per:g} pts", f"each: price above {TREND_ABOVE_POINTS:g} + average rising {TREND_RISING_POINTS:g}"],
    )


def _continuity_component(green: list[str]) -> Component:
    full = len(green) == 3
    points = sum(TF_GREEN_POINTS[tf] for tf in green) + (FULL_GREEN_BONUS if full else 0.0)
    detail = " · ".join(f"{tf} +{TF_GREEN_POINTS[tf]:g}" for tf in green) or "no timeframe green"
    if full:
        detail += f" · all three +{FULL_GREEN_BONUS:g}"
    red = [tf for tf in ("M", "W", "D") if tf not in green]
    if red:
        detail += f" ({'/'.join(red)} not green)"
    subs = [" · ".join(f"{tf} {v:g}" for tf, v in TF_GREEN_POINTS.items()) + f" · all three +{FULL_GREEN_BONUS:g}"]
    return _c("continuity", "Continuity", points, CONTINUITY_POINTS, detail, subs)


def _theme_component(theme: Optional[ThemeStrength], theme_name: str) -> Component:
    label = "Theme strength"
    if theme is None:
        detail = f"no Themes-page score for {theme_name} yet" if theme_name else "not in any theme"
        return _c("theme_strength", label, 0.0, THEME_POINTS, detail)
    rank = f"#{theme.rank} of {theme.total}"
    return _c(
        "theme_strength", f"{label} · {theme.name} ({rank})", theme_strength_points(theme), THEME_POINTS,
        f"{theme.name}: leadership score {theme.score:.1f}, {rank} themes; "
        f"{THEME_POINTS:g} × ({theme.total} − {theme.rank} + 1) / {theme.total}",
    )


def theme_strength_points(strength: Optional[ThemeStrength]) -> float:
    if strength is None or strength.total <= 0:
        return 0.0
    return THEME_POINTS * (strength.total - strength.rank + 1) / strength.total


def _long_rs_component(momentum: Optional[Momentum]) -> Component:
    c = leadership_scoring._rs_component(momentum)
    c = _scaled(c, LONG_RS_POINTS)
    c.label = c.label.replace("Relative strength", "Long RS")
    c.detail = c.detail.replace(f"{leadership_scoring.RS_POINTS:g} ×", f"{LONG_RS_POINTS:g} ×")
    return c


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
    trend_break: Optional[Breakdown] = None,
    kill: Optional[KillCandle] = None,
    base: Optional[BaseMetrics] = None,
    srs: Optional[ShortRS] = None,
    peers: int = 0,
) -> Score:
    """The scan part of the setup score (stocks and ETFs). Entry parts are added by :func:`entry_score`."""
    trend_break = trend_break or Breakdown("none")
    parts: list[Component] = []
    parts += tightness_components(base)
    parts += short_rs_components(srs, peers)
    parts.append(_trend_component(trend))

    daily = states.get(SETUP_TF)
    scored = [
        ScoredSetup(SETUP_TF, setup, SETUP_POINTS.get(setup.kind, 0.0)) for setup in (daily.setups if daily else [])
    ]
    ordered = sorted(scored, key=lambda s: s.points, reverse=True)
    primary = _pick_primary(scored, price)
    dist = trigger_distance_pct(price, primary.setup.trigger, primary.setup.side) if primary else None
    colors = {tf: continuity_color(s) for tf, s in states.items()}
    green = [tf for tf in ("M", "W", "D") if colors.get(tf) == "green"]
    full = len(green) == 3
    mw_green = "M" in green and "W" in green
    monthly = states.get("M")
    monthly_2u = bool(monthly and monthly.strat == TWO_UP)
    parts.append(_continuity_component(green))
    parts.append(_c(
        "liquidity", "Liquidity", liquidity_points(avg_dollar_volume) * LIQUIDITY_POINTS / 10.0, LIQUIDITY_POINTS,
        f"avg ${avg_dollar_volume / 1e6:,.0f}M/day (log scale, 0 at $50M, max at $5B)",
    ))
    if kind == "stock":
        parts.append(_theme_component(theme, theme_name))
    parts.append(_long_rs_component(momentum))

    max_raw = max_scan_points(kind)
    _weigh(parts, max_raw)
    raw = sum(c.points for c in parts)
    keep = 1.0
    if trend_break.level in (BROKEN, WARNING):
        k = leadership_scoring.BROKEN_FACTOR if trend_break.level == BROKEN else leadership_scoring.WARNING_FACTOR
        label = "Breakdown penalty" if trend_break.level == BROKEN else "Weakening penalty"
        parts.append(_c("breakdown", label, -raw * (1 - k), 0.0, "; ".join(trend_break.reasons) + f" — score × {k:g}"))
        raw *= k
        keep *= k
    if kill is not None and kill.penalty > 0:
        parts.append(leadership_scoring._kill_component(kill, raw))
        raw *= 1 - kill.penalty
        keep *= 1 - kill.penalty
    if atr_pct is not None and atr_pct < MIN_ATR_PCT:
        penalty = -raw * (1 - PINNED_PENALTY)
        parts.append(_c("pinned", "Pinned penalty", penalty, 0.0, f"avg daily range {atr_pct:.2f}% < {MIN_ATR_PCT}%, score halved"))
        raw += penalty
        keep *= PINNED_PENALTY

    reasons: list[str] = []
    if primary:
        reasons.append(_describe(primary, dist))
        reasons.extend(f"Daily {s.setup.label}" for s in ordered if s is not primary)
    else:
        reasons.append("No daily setup")
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
    if base is not None and (base.inside_day or base.nr7):
        reasons.append("Inside day" if base.inside_day else "NR7")
    if srs is not None and srs.rs_line_high and not srs.price_high:
        reasons.append("RS line at a 20-day high before price")
    if kill is not None and kill.penalty > 0:
        reasons.append(f"Kill candle {kill.date} (score -{kill.penalty * 100:.0f}%)")
    if trend_break.level != "none":
        reasons.append(("Broken: " if trend_break.level == BROKEN else "Weakening: ") + "; ".join(trend_break.reasons))
    if atr_pct is not None and atr_pct < MIN_ATR_PCT:
        reasons.append(f"Very low volatility (avg range {atr_pct:.2f}%), possibly pinned by a deal")

    rs = momentum.blended if momentum else None
    inputs = {
        "base": asdict(base) if base else None,
        "short_rs": asdict(srs) if srs else None,
        "rs_blended": rs,
        "theme_rank": [theme.rank, theme.total] if theme else None,
    }
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
        keep=keep,
        inputs=inputs,
    )


def _weigh(parts: list[Component], max_raw: float) -> None:
    for c in parts:
        c.weight_pct = round(c.max_points / max_raw * 100.0, 1) if c.max_points else 0.0


# ---------------------------------------------------------------------------------------------------- entry parts


@dataclass(frozen=True)
class EntryInputs:
    """What only the 15-minute trigger knows."""

    stop_pct: Optional[float] = None  # (trigger - stop) / trigger, %
    atr14_pct: Optional[float] = None  # the scan row's ATR(14) %
    stock_change_pct: Optional[float] = None  # open to the trigger bar's close
    qqq_change_pct: Optional[float] = None  # QQQ over the same window
    day_volume: Optional[float] = None  # today's volume through the trigger bar
    avg_volume: Optional[float] = None  # 20-day average daily volume
    bars_elapsed: Optional[int] = None  # completed 15-minute bars through the trigger bar

    @property
    def stop_x_atr(self) -> Optional[float]:
        if self.stop_pct is None or not self.atr14_pct:
            return None
        return self.stop_pct / self.atr14_pct

    @property
    def intraday_excess(self) -> Optional[float]:
        if self.stock_change_pct is None or self.qqq_change_pct is None:
            return None
        return self.stock_change_pct - self.qqq_change_pct

    @property
    def intraday_excess_x_atr(self) -> Optional[float]:
        ex = self.intraday_excess
        return None if ex is None or not self.atr14_pct else ex / self.atr14_pct

    @property
    def relative_volume(self) -> Optional[float]:
        if not self.day_volume or not self.avg_volume or not self.bars_elapsed:
            return None
        return self.day_volume / (self.avg_volume * min(1.0, self.bars_elapsed / SESSION_BARS_15M))


def entry_components(e: EntryInputs) -> list[Component]:
    sx, ex, rv = e.stop_x_atr, e.intraday_excess_x_atr, e.relative_volume
    return [
        _c(
            "stop_atr", f"Stop vs ATR · {_fmt(sx)}×", STOP_ATR_POINTS * frac(sx, *STOP_ATR_RANGE), STOP_ATR_POINTS,
            f"stop {_fmt(e.stop_pct)}% / ATR(14) {_fmt(e.atr14_pct)}% = {_fmt(sx)} "
            f"(full at ≤{STOP_ATR_RANGE[0]:g}, none at ≥{STOP_ATR_RANGE[1]:g})",
        ),
        _c(
            "trigger_volume", f"Trigger-day volume · {_fmt(rv)}×",
            TRIGGER_VOLUME_POINTS * frac(rv, *TRIGGER_VOLUME_RANGE), TRIGGER_VOLUME_POINTS,
            f"volume through the trigger bar vs the 20-day average pro-rated over {_fmt(e.bars_elapsed, 'd')} of "
            f"{SESSION_BARS_15M} bars = {_fmt(rv)} (full at ≥{TRIGGER_VOLUME_RANGE[0]:g}, none at ≤{TRIGGER_VOLUME_RANGE[1]:g})",
        ),
        _c(
            "intraday_rs", f"Intraday RS · {_fmt(e.intraday_excess, '+.2f')} pts",
            INTRADAY_RS_POINTS * frac(ex, *INTRADAY_RS_RANGE), INTRADAY_RS_POINTS,
            f"open to trigger bar {_fmt(e.stock_change_pct, '+.2f')}% vs QQQ {_fmt(e.qqq_change_pct, '+.2f')}% = "
            f"{_fmt(e.intraday_excess, '+.2f')} pts = {_fmt(ex, '+.2f')} ATR (full at ≥{INTRADAY_RS_RANGE[0]:g} ATR, none at ≤0)",
        ),
    ]


def entry_score(row: Optional[Mapping[str, Any]], entry: EntryInputs) -> dict:
    """The full 0-100 score of one trade: the scan row's components (as they were when the alert fired) plus the
    entry parts, with every raw input. Frozen on the alert as ``details["score"]``.

    The scan's penalties (breakdown, kill candle, pinned) scale the entry parts the same way. A name off the scan
    (``row`` None, e.g. an off-universe inverse ETF) gets the entry parts alone.
    """
    kind = (row or {}).get("kind") or "stock"
    scan_parts = [dict(c) for c in ((row or {}).get("score_breakdown") or [])]
    keep = float((row or {}).get("score_keep") or 1.0)
    scan_raw = float((row or {}).get("score_raw") or 0.0)
    has_scan = bool(scan_parts)
    max_raw = max_entry_points(kind) if has_scan else ENTRY_MAX_POINTS
    entry_parts = entry_components(entry)
    entry_raw = sum(c.points for c in entry_parts) * keep
    _weigh(entry_parts, max_raw)
    parts = []
    for c in scan_parts:
        c["weight_pct"] = round(float(c.get("max_points") or 0) / max_raw * 100.0, 1)
        parts.append(c)
    for c in entry_parts:
        parts.append({
            "key": c.key, "label": c.label, "points": round(c.points * keep, 3), "max_points": c.max_points,
            "weight_pct": c.weight_pct, "sub_weights": c.sub_weights, "detail": c.detail, "entry": True,
        })
    raw = scan_raw + entry_raw
    groups = {}
    for g, keys in GROUPS.items():
        got = [p for p in parts if p["key"] in keys]
        if got:
            groups[g] = {"points": round(sum(p["points"] for p in got), 3), "max": sum(p["max_points"] for p in got)}
    return {
        "version": VERSION,
        "score": round(max(0.0, min(100.0, raw * 100.0 / max_raw)), 1),
        "raw": round(raw, 3),
        "max_raw": max_raw,
        "scan_score": (row or {}).get("score"),
        "scan_as_of": (row or {}).get("as_of"),
        "keep": keep,
        "groups": groups,
        "components": {p["key"]: round(float(p["points"]), 3) for p in parts},
        "breakdown": parts,
        "inputs": {
            **((row or {}).get("score_inputs") or {}),
            "entry": {
                **asdict(entry),
                "stop_x_atr": entry.stop_x_atr,
                "intraday_excess": entry.intraday_excess,
                "intraday_excess_x_atr": entry.intraday_excess_x_atr,
                "relative_volume": entry.relative_volume,
            },
        },
    }


VERSION = 1  # bump when the weights or ranges change, so the report can split trades by version


# ------------------------------------------------------------------------------------------ cross-section helpers


def rank_short_rs(values: Mapping[str, Mapping[str, ShortRS]]) -> dict[str, dict[str, ShortRS]]:
    """Fill the 10 / 20-day percentiles within each peer group (``values``: group -> symbol -> ShortRS)."""
    from bisect import bisect_left, bisect_right

    out: dict[str, dict[str, ShortRS]] = {}
    for group, by_symbol in values.items():
        dists = {
            n: sorted(v for s in by_symbol.values() if (v := getattr(s, f"excess_{n}d")) is not None)
            for n in SHORT_RS_PERIODS
        }

        def pct(n: int, v: Optional[float]) -> Optional[float]:
            ordered = dists[n]
            if v is None or not ordered:
                return None
            less = bisect_left(ordered, v)
            return (less + 0.5 * (bisect_right(ordered, v) - less)) / len(ordered)

        out[group] = {
            sym: ShortRS(
                s.excess_10d, s.excess_20d, pct(10, s.excess_10d), pct(20, s.excess_20d), s.rs_line_high, s.price_high
            )
            for sym, s in by_symbol.items()
        }
    return out


__all__ = [
    "BaseMetrics", "ShortRS", "EntryInputs", "Score", "base_metrics", "short_rs", "rank_short_rs", "score_symbol",
    "entry_score", "entry_components", "theme_strength_points", "STOCK_SCAN_MAX", "STOCK_ENTRY_MAX", "GROUPS",
    "PERIODS", "PERIOD_LABELS", "MOMENTUM_WEIGHTS",
]
