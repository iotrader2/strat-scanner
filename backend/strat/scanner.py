"""Run the Strat scan over every cached symbol."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

import pandas as pd

from . import config
from .candles import Candle, TimeframeState, classify_series, is_hammer, timeframe_state
from .data import resample
from .scoring import TF_NAMES, SectorStrength, score_symbol, sector_strength_points
from .universe import SECTOR_ETFS, Member

TIMEFRAMES = ("M", "W", "D")


def to_candles(df: pd.DataFrame) -> list[Candle]:
    return [Candle(r.open, r.high, r.low, r.close) for r in df.itertuples()]


def _tf_payload(st: Optional[TimeframeState]) -> Optional[dict]:
    if st is None:
        return None
    d = asdict(st)
    del d["setups"]
    return d


def sector_strengths(rows: list[dict]) -> dict[str, SectorStrength]:
    """Rank the sector and industry ETFs (not benchmarks) by score, as on the Sectors page."""
    by_symbol = {r["symbol"]: r for r in rows}
    candidates = [(by_symbol[sym], name) for sym, name, _, _ in SECTOR_ETFS if sym in by_symbol]
    ranked = sorted(candidates, key=lambda rn: (-rn[0]["score"], rn[0]["symbol"]))
    if not ranked:
        return {}
    top = ranked[0][0]
    return {
        r["symbol"]: SectorStrength(r["symbol"], name, r["score"], i, len(ranked), top["symbol"], top["score"])
        for i, (r, name) in enumerate(ranked, start=1)
    }


def scan_symbol(member: Member, daily: pd.DataFrame, sectors: Optional[dict[str, SectorStrength]] = None) -> Optional[dict]:
    """Scan one symbol; stocks get Sector strength from ``sectors`` (see ``sector_strengths``)."""
    if daily is None or len(daily) < 30:
        return None
    states = {tf: timeframe_state(tf, to_candles(resample(daily, tf))) for tf in TIMEFRAMES}
    last = daily.iloc[-1]
    price = float(last.close)
    recent = daily.tail(config.ADV_LOOKBACK_DAYS)
    adv = float((recent.close * recent.volume).mean())
    avg_volume = float(recent.volume.mean())
    atr_pct = float(((recent.high - recent.low) / recent.close).mean() * 100)
    prev_close = float(daily.close.iloc[-2]) if len(daily) > 1 else price

    strength_etf = member.strength_etf
    strength = (sectors or {}).get(strength_etf)
    sc = score_symbol(states, price, adv, atr_pct, kind=member.kind, sector=strength, sector_etf=strength_etf)
    primary = sc.primary
    return {
        "symbol": member.symbol,
        "name": member.name,
        "sector": member.sector,
        "sector_etf": member.sector_etf,
        "industry": member.industry,
        "strength_etf": strength_etf or None,
        "sector_strength": (
            {
                "etf": strength.etf,
                "name": strength.name,
                "score": strength.score,
                "rank": strength.rank,
                "total": strength.total,
                "points": round(sector_strength_points(strength), 2),
            }
            if strength
            else None
        ),
        "kind": member.kind,
        "indexes": member.indexes,
        "in_universe": member.in_universe,
        "price": round(price, 2),
        "change_pct": round((price / prev_close - 1) * 100, 2) if prev_close else 0.0,
        "avg_dollar_volume": adv,
        "avg_volume": avg_volume,
        "atr_pct": round(atr_pct, 2),
        "as_of": daily.index[-1].strftime("%Y-%m-%d"),
        "score": sc.score,
        "score_raw": sc.raw,
        "score_max_raw": sc.max_raw,
        "score_breakdown": [
            {
                "key": c.key,
                "label": c.label,
                "points": round(c.points, 2),
                "max_points": c.max_points,
                "detail": c.detail,
            }
            for c in sc.breakdown
        ],
        "full_continuity": sc.full_continuity,
        "mw_green": sc.mw_green,
        "monthly_2u": sc.monthly_2u,
        "has_setup": sc.has_setup,
        "trigger": round(primary.setup.trigger, 2) if primary else None,
        "trigger_tf": primary.tf if primary else None,
        "setup": f"{TF_NAMES[primary.tf]} {primary.setup.label}" if primary else None,
        "triggered": primary.setup.triggered if primary else None,
        "trigger_distance_pct": sc.trigger_distance_pct,
        "reason": " · ".join(sc.reasons),
        "setups": [
            {"tf": s.tf, "points": s.points, **asdict(s.setup)}
            for s in sorted(sc.setups, key=lambda s: s.points, reverse=True)
        ],
        "tf": {tf: _tf_payload(states[tf]) for tf in TIMEFRAMES},
    }


def scan_all(members: list[Member], daily_by_symbol: dict[str, pd.DataFrame]) -> list[dict]:
    """Scan ETFs first so their scores can rank the sectors that feed each stock's Sector strength."""
    etf_rows = [scan_symbol(m, daily_by_symbol.get(m.symbol)) for m in members if m.kind == "etf"]
    rows = [r for r in etf_rows if r]
    sectors = sector_strengths(rows)
    for m in members:
        if m.kind != "etf":
            row = scan_symbol(m, daily_by_symbol.get(m.symbol), sectors)
            if row:
                rows.append(row)
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


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


def sector_entries(
    etfs: list[tuple[str, str, str, str]],
    rows_by_symbol: dict[str, dict],
    daily_by_symbol: dict[str, pd.DataFrame],
    tf: str,
    bars: int,
) -> list[dict]:
    """Sector ETF cards for one timeframe, strongest score first (ties by symbol)."""
    out = etf_cards(etfs, rows_by_symbol, daily_by_symbol, tf, bars)
    out.sort(key=lambda e: (-e["row"]["score"], e["symbol"]))
    return out


def etf_cards(
    etfs: list[tuple[str, str, str, str]],
    rows_by_symbol: dict[str, dict],
    daily_by_symbol: dict[str, pd.DataFrame],
    tf: str,
    bars: int,
) -> list[dict]:
    """ETF cards (scan row + chart candles) in the order given; ETFs without data are skipped."""
    out = []
    for sym, name, sector, group in etfs:
        daily = daily_by_symbol.get(sym)
        row = rows_by_symbol.get(sym)
        if daily is None or row is None:
            continue
        out.append(
            {
                "symbol": sym,
                "name": name,
                "sector": sector,
                "group": group,
                "row": row,
                "candles": chart_payload(daily, tf, bars),
            }
        )
    return out
