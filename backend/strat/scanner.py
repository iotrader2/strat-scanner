"""Run the Strat scan over every cached symbol."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Optional

import pandas as pd

from . import config
from .change import (
    RS_LOOKBACK,
    STATE_LOOKBACK,
    PriorRanks,
    entered_leaders,
    prior_ranks,
    rs_change_points,
    session_calendar,
    snapshot,
    worsened,
)
from .candles import Candle, TimeframeState, classify_series, is_hammer, timeframe_state
from .data import resample
from .periods import completed_week_high_labels
from . import legacy_scoring, scoring
from .leadership import (
    BENCHMARK,
    assess_breakdown,
    qqq_excess,
    leader_status,
    long_term_rs,
    nearest_trigger,
    trend_metrics,
)
from .breakout import MIN_RS as MIN_BREAKOUT_RS, find_breakout, find_failed_breakout
from .macd import latest_daily_trend
from .perf import MomentumRanks, Perf, period_returns
from .pricebehavior import find_kill_candle, range_stats, tightness_fraction
from .quotes import IndexQuote, percent_change
from .scoring import TF_NAMES, ThemeStrength, trigger_distance_pct
from .themes import Theme, ThemeMap, build_theme_index
from .universe import Member

TIMEFRAMES = ("M", "W", "D")
HIGHER_TFS = ("3M", "6M")  # shown on the index cards, not part of the score
LEADERS = "leaders"
LEGACY = "legacy"  # the previous Strat-first score, for the backtest comparison only
ATR_PERIOD = 14


def average_true_range(daily: pd.DataFrame, period: int = ATR_PERIOD) -> tuple[float, float]:
    """14-day average true range in dollars, and that range as a percent of the last close."""
    prev = daily.close.shift(1)
    tr = pd.concat([daily.high, prev], axis=1).max(axis=1) - pd.concat([daily.low, prev], axis=1).min(axis=1)
    window = tr.dropna().tail(period)
    atr = float(window.mean()) if len(window) else 0.0
    price = float(daily.close.iloc[-1])
    return atr, (atr / price * 100) if price else 0.0


def to_candles(df: pd.DataFrame) -> list[Candle]:
    return [Candle(r.open, r.high, r.low, r.close) for r in df.itertuples()]


def _tf_payload(st: Optional[TimeframeState]) -> Optional[dict]:
    if st is None:
        return None
    d = asdict(st)
    del d["setups"]
    return d


def theme_strengths(theme_rows: Mapping[str, dict], themes: Optional[ThemeMap] = None) -> dict[str, ThemeStrength]:
    """Rank the themes by score (ties by name), as on the Themes page; rank 1 is the strongest."""
    names = {t.id: t.name for t in themes.themes} if themes else {}
    ranked = sorted(theme_rows.values(), key=lambda r: (-r["score"], r["name"]))
    if not ranked:
        return {}
    top = ranked[0]
    return {
        r["symbol"]: ThemeStrength(
            r["symbol"], names.get(r["symbol"], r["name"]), r["score"], i, len(ranked), top["symbol"], top["score"], top["name"]
        )
        for i, r in enumerate(ranked, start=1)
    }


def theme_member(theme: Theme) -> Member:
    """The scan identity of a theme's equal-weight index (kind "theme", symbol = theme id)."""
    return Member(theme.id, theme.name, "Theme", "theme", "THEME")


def scan_symbol(
    member: Member,
    daily: pd.DataFrame,
    strengths: Optional[Mapping[str, ThemeStrength]] = None,
    ranks: Optional[MomentumRanks] = None,
    themes: Optional[ThemeMap] = None,
    qqq: Optional[Perf] = None,
    method: str = LEADERS,
    prior: Optional[Mapping[int, PriorRanks]] = None,
) -> Optional[dict]:
    """Scan one symbol.

    ``ranks`` supplies the peer distributions for relative strength and ``qqq`` the QQQ returns; stocks
    also get Theme strength from ``strengths`` (see ``theme_strengths``) for their primary theme in ``themes``.
    ``method`` is ``"leaders"`` (the leadership-first score) or ``"legacy"`` (the old Strat-first score).
    ``prior`` supplies the peer distributions at earlier sessions (see ``change.prior_ranks``) for the RS change and the
    new breakdown / new leader flags; without it those fields are empty.
    """
    if daily is None or len(daily) < 30:
        return None
    candles = {tf: to_candles(resample(daily, tf)) for tf in TIMEFRAMES}
    states = {tf: timeframe_state(tf, candles[tf]) for tf in TIMEFRAMES}
    last = daily.iloc[-1]
    price = float(last.close)
    recent = daily.tail(config.ADV_LOOKBACK_DAYS)
    adv = float((recent.close * recent.volume).mean())
    avg_volume = float(recent.volume.mean())
    range_pct = float(((recent.high - recent.low) / recent.close).mean() * 100)
    atr, atr_pct = average_true_range(daily)
    # Last bar versus the one before it. In the regular session the last bar is today,
    # so this is today's move versus the prior close. Before the open the last bar is
    # still the previous session, so this is that session's move; the index cards
    # replace it with the live print (see quotes.py).
    prev_close = float(daily.close.iloc[-2]) if len(daily) > 1 else price

    perf = period_returns(daily.close)
    momentum = ranks.momentum(member.kind, perf) if ranks else None
    theme = themes.theme_of(member.symbol) if themes and member.kind == "stock" else None
    strength = (strengths or {}).get(theme.id) if theme else None
    secondary = themes.secondary.get(member.symbol, []) if themes and member.kind == "stock" else []
    secondary_names = [themes.by_id(t).name for t in secondary] if themes else []
    trend = trend_metrics(daily)
    excess = qqq_excess(perf, qqq)
    long_rs = long_term_rs(momentum.percentiles) if momentum else None
    trend_break = assess_breakdown(trend, perf, long_rs)
    tightness = range_stats(daily)
    kill = find_kill_candle(daily)
    breakout = find_breakout(daily, kill) if member.kind == "stock" and ((momentum.blended if momentum else None) or 0) >= MIN_BREAKOUT_RS else None
    failed_breakout = find_failed_breakout(daily) if member.kind == "stock" else None
    if method == LEGACY:
        sc = legacy_scoring.score_symbol(
            states, price, adv, range_pct, kind=member.kind, theme=strength, momentum=momentum,
            theme_name=theme.name if theme else "",
        )
        theme_points = legacy_scoring.theme_strength_points
    else:
        sc = scoring.score_symbol(
            states, price, adv, range_pct, kind=member.kind, theme=strength, momentum=momentum,
            theme_name=theme.name if theme else "", trend=trend, excess=excess, trend_break=trend_break,
            tightness=tightness, kill=kill,
        )
        theme_points = scoring.theme_strength_points
    primary = sc.primary
    rs = momentum.blended if momentum else None
    status = leader_status(rs, trend_break)
    as_of = daily.index[-1].strftime("%Y-%m-%d")
    history = [
        snap
        for k, pr in (prior or {}).items()
        if (snap := snapshot(member.kind, daily, pr, with_level=k <= STATE_LOOKBACK)) is not None
    ]
    rs_then = next((s for s in history if s.offset == RS_LOOKBACK), None)
    rs_prev = rs_then.rs if rs_then else None
    new_breakdown = worsened(trend_break.level, history, as_of)
    new_leader = entered_leaders(rs, trend_break.level, history, as_of)
    near = None
    if primary is None and candles["W"]:
        recent, prior = completed_week_high_labels(daily.index[-1].date())
        weekly = candles["W"]
        levels = [(weekly[-1].high, recent)] + ([(weekly[-2].high, prior)] if len(weekly) > 1 else [])
        near = nearest_trigger(price, levels)
    return {
        "symbol": member.symbol,
        "name": member.name,
        "sector": member.sector,
        "sector_etf": member.sector_etf,
        "industry": member.industry,
        "theme": theme.id if theme else None,
        "theme_name": theme.name if theme else None,
        "secondary_themes": secondary,
        "secondary_theme_names": secondary_names,
        "theme_strength": (
            {
                "theme": strength.theme,
                "name": strength.name,
                "score": strength.score,
                "rank": strength.rank,
                "total": strength.total,
                "points": round(theme_points(strength), 2),
            }
            if strength
            else None
        ),
        "perf": perf,
        "rs": None if rs is None else round(rs, 4),
        "rs_prev": None if rs_prev is None else round(rs_prev, 4),
        "rs_prev_date": rs_then.date if rs_then and rs_prev is not None else None,
        "rs_change": rs_change_points(rs, rs_prev),
        "leader_status": status,
        "is_leader": status == "leader",
        "leadership": {
            "rs": None if rs is None else round(rs, 4),
            "status": status,
            "excess": excess,
            "above_ma": {str(p): trend.above(p) if trend else None for p in (10, 20, 50)},
            "off_52w_high_pct": trend.off_52w_high_pct if trend else None,
            "off_6m_high_pct": trend.off_6m_high_pct if trend else None,
            "breakdown": trend_break.level,
            "breakdown_reasons": trend_break.reasons,
            "breakdown_new": new_breakdown,
            "leader_new": new_leader,
        },
        "tightness": (
            {
                "range10_pct": round(tightness.range10_pct, 2),
                "range50_pct": round(tightness.range50_pct, 2),
                "ratio": round(tightness.ratio, 3),
                "contraction": round(tightness.contraction, 3),
                "fraction": round(tightness_fraction(tightness), 3),
            }
            if tightness
            else None
        ),
        "kill_candle": asdict(kill) if kill else None,
        "breakout": asdict(breakout) if breakout else None,
        "failed_breakout": asdict(failed_breakout) if failed_breakout else None,
        "kind": member.kind,
        "indexes": member.indexes,
        "in_universe": member.in_universe,
        "price": round(price, 2),
        "change_pct": percent_change(price, prev_close),
        "avg_dollar_volume": adv,
        "avg_volume": avg_volume,
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "as_of": as_of,
        "score": sc.score,
        "score_raw": sc.raw,
        "score_max_raw": sc.max_raw,
        "score_breakdown": [
            {
                "key": c.key,
                "label": c.label,
                "points": round(c.points, 2),
                "max_points": c.max_points,
                "weight_pct": c.weight_pct,
                "sub_weights": c.sub_weights,
                "detail": c.detail,
            }
            for c in sc.breakdown
        ],
        "full_continuity": sc.full_continuity,
        "mw_green": sc.mw_green,
        "monthly_2u": sc.monthly_2u,
        "has_setup": sc.has_setup,
        # Same daily frame as the D badge, including today's session bar when it is overlaid.
        "daily_trend": latest_daily_trend(daily),
        "trigger": round(primary.setup.trigger, 2) if primary else None,
        "trigger_tf": primary.tf if primary else None,
        "setup": f"{TF_NAMES[primary.tf]} {primary.setup.label}" if primary else None,
        "triggered": primary.setup.triggered if primary else None,
        "trigger_distance_pct": sc.trigger_distance_pct,
        "nearest_trigger": round(near[0], 2) if near else None,
        "nearest_trigger_label": near[1] if near else None,
        "nearest_trigger_distance_pct": round(trigger_distance_pct(price, near[0]), 2) if near else None,
        "reason": " · ".join(sc.reasons),
        "setups": [
            {"tf": s.tf, "points": s.points, **asdict(s.setup)}
            for s in sorted(sc.setups, key=lambda s: s.points, reverse=True)
        ],
        "tf": {tf: _tf_payload(states[tf]) for tf in TIMEFRAMES},
    }


@dataclass
class ScanResult:
    rows: list[dict]  # stocks and ETFs, strongest first
    theme_rows: dict[str, dict] = field(default_factory=dict)  # theme id -> scan row of its equal-weight index
    theme_daily: dict[str, pd.DataFrame] = field(default_factory=dict)  # theme id -> index OHLC
    strengths: dict[str, ThemeStrength] = field(default_factory=dict)
    ranks: MomentumRanks = field(default_factory=lambda: MomentumRanks({}))
    themes: Optional[ThemeMap] = None
    qqq: dict[str, Optional[float]] = field(default_factory=dict)  # QQQ returns
    method: str = LEADERS
    prior: dict[int, PriorRanks] = field(default_factory=dict)  # peer distributions at earlier sessions


MIN_THEME_MEMBERS_WITH_DATA = 2


def scan_all(
    members: list[Member],
    daily_by_symbol: dict[str, pd.DataFrame],
    themes: Optional[ThemeMap] = None,
    method: str = LEADERS,
    changes: bool = True,
) -> ScanResult:
    """Scan everything. Order matters: returns are ranked first (relative strength), then the themes are scored and
    ranked, and only then the stocks, whose Theme strength comes from their theme's rank. ``changes`` adds the RS change
    and new breakdown / new leader flags (4 extra ranking passes over earlier sessions; the backtest turns it off)."""
    perf_by_group: dict[str, dict[str, Perf]] = {"stock": {}, "etf": {}, "theme": {}}
    for m in members:
        daily = daily_by_symbol.get(m.symbol)
        if m.kind in perf_by_group and daily is not None and len(daily) >= 30:
            perf_by_group[m.kind][m.symbol] = period_returns(daily.close)

    theme_daily: dict[str, pd.DataFrame] = {}
    for theme in themes.themes if themes else []:
        have = [s for s in theme.members if daily_by_symbol.get(s) is not None]
        index = build_theme_index(daily_by_symbol, have) if len(have) >= MIN_THEME_MEMBERS_WITH_DATA else None
        if index is not None and len(index) >= 30:
            theme_daily[theme.id] = index
            perf_by_group["theme"][theme.id] = period_returns(index.close)
    ranks = MomentumRanks.from_perf(perf_by_group)
    bench_daily = daily_by_symbol.get(BENCHMARK)
    qqq = period_returns(bench_daily.close) if bench_daily is not None and len(bench_daily) >= 30 else {}

    prior: dict[int, PriorRanks] = {}
    if changes:
        groups: dict[str, dict[str, pd.DataFrame]] = {"stock": {}, "etf": {}, "theme": dict(theme_daily)}
        for kind in ("stock", "etf"):
            groups[kind] = {s: daily_by_symbol[s] for s in perf_by_group[kind]}
        prior = prior_ranks(session_calendar(daily_by_symbol), groups)

    theme_rows = {}
    for theme in themes.themes if themes else []:
        if theme.id in theme_daily:
            row = scan_symbol(theme_member(theme), theme_daily[theme.id], ranks=ranks, qqq=qqq, method=method, prior=prior)
            if row:
                theme_rows[theme.id] = row
    strengths = theme_strengths(theme_rows, themes)

    rows = []
    for m in members:
        if m.kind != "theme":
            row = scan_symbol(m, daily_by_symbol.get(m.symbol), strengths, ranks, themes, qqq, method, prior)
            if row:
                rows.append(row)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return ScanResult(rows, theme_rows, theme_daily, strengths, ranks, themes, qqq, method, prior)


def chart_payload(daily: pd.DataFrame, tf: str, limit: int) -> list[dict]:
    """Candles with their Strat number and hammer flag, for the chart markers."""
    df = resample(daily, tf)
    candles = to_candles(df)
    types = classify_series(candles)
    out = []
    for (ts, row), c, t in zip(df.iterrows(), candles, types):
        out.append(
            {
                "time": ts.strftime("%Y-%m-%d"),
                "open": round(c.open, 4),
                "high": round(c.high, 4),
                "low": round(c.low, 4),
                "close": round(c.close, 4),
                "volume": float(row.volume),
                "strat": t,
                "hammer": is_hammer(c),
            }
        )
    return out[-limit:]


def _chip(row: dict, also: bool) -> dict:
    return {
        "symbol": row["symbol"],
        "name": row["name"],
        "change_pct": row["change_pct"],
        "perf": row["perf"],
        "score": row["score"],
        "mw_green": row["mw_green"],
        "has_setup": row["has_setup"],
        "also": also,
    }


def theme_cards(result: ScanResult, rows_by_symbol: Mapping[str, dict], tf: str, bars: int) -> list[dict]:
    """One card per theme for a timeframe, strongest score first: index candles, scan row and member chips."""
    out = []
    for theme in result.themes.themes if result.themes else []:
        row = result.theme_rows.get(theme.id)
        if row is None:
            continue
        primary = [_chip(rows_by_symbol[s], False) for s in theme.members if s in rows_by_symbol]
        also = [_chip(rows_by_symbol[s], True) for s in theme.also if s in rows_by_symbol]
        primary.sort(key=lambda c: (-c["score"], c["symbol"]))
        also.sort(key=lambda c: (-c["score"], c["symbol"]))
        out.append(
            {
                "id": theme.id,
                "name": theme.name,
                "description": theme.description,
                "count": len(primary),
                "members": primary,
                "also": also,
                "row": row,
                "candles": chart_payload(result.theme_daily[theme.id], tf, bars),
            }
        )
    out.sort(key=lambda c: (-c["row"]["score"], c["name"]))
    return out


def etf_cards(
    etfs: list[tuple[str, str, str, str]],
    rows_by_symbol: dict[str, dict],
    daily_by_symbol: dict[str, pd.DataFrame],
    tf: str,
    bars: int,
    quotes: Optional[Mapping[str, IndexQuote]] = None,
) -> list[dict]:
    """ETF cards (scan row + chart candles) in the order given; ETFs without data are skipped.

    ``quotes`` overlays a premarket or after-hours price on the card only. The scan row
    itself is left alone, and ``session`` is the badge (``None`` during the regular session).
    """
    out = []
    for sym, name, sector, group in etfs:
        daily = daily_by_symbol.get(sym)
        row = rows_by_symbol.get(sym)
        if daily is None or row is None:
            continue
        higher = dict(row.get("tf") or {})
        for period in HIGHER_TFS:
            higher[period] = _tf_payload(timeframe_state(period, to_candles(resample(daily, period))))
        shown = {**row, "tf": higher}
        quote = (quotes or {}).get(sym)
        session = None
        if quote is not None:
            shown = {**shown, "price": quote.price, "change_pct": quote.change_pct}
            session = quote.session
        out.append(
            {
                "symbol": sym,
                "name": name,
                "sector": sector,
                "group": group,
                "row": shown,
                "session": session,
                "candles": chart_payload(daily, tf, bars),
            }
        )
    return out
