"""Run the Strat scan over every cached symbol."""

from __future__ import annotations

from dataclasses import asdict
from typing import Optional

import pandas as pd

from . import config
from .candles import Candle, TimeframeState, classify_series, is_hammer, timeframe_state
from .data import resample
from .scoring import TF_NAMES, score_symbol
from .universe import Member

TIMEFRAMES = ("M", "W", "D")


def to_candles(df: pd.DataFrame) -> list[Candle]:
    return [Candle(r.open, r.high, r.low, r.close) for r in df.itertuples()]


def _tf_payload(st: Optional[TimeframeState]) -> Optional[dict]:
    if st is None:
        return None
    d = asdict(st)
    del d["setups"]
    return d


def scan_symbol(member: Member, daily: pd.DataFrame) -> Optional[dict]:
    if daily is None or len(daily) < 30:
        return None
    states = {tf: timeframe_state(tf, to_candles(resample(daily, tf))) for tf in TIMEFRAMES}
    last = daily.iloc[-1]
    price = float(last.close)
    recent = daily.tail(config.ADV_LOOKBACK_DAYS)
    adv = float((recent.close * recent.volume).mean())
    atr_pct = float(((recent.high - recent.low) / recent.close).mean() * 100)
    prev_close = float(daily.close.iloc[-2]) if len(daily) > 1 else price

    sc = score_symbol(states, price, adv, atr_pct)
    primary = sc.primary
    return {
        "symbol": member.symbol,
        "name": member.name,
        "sector": member.sector,
        "sector_etf": member.sector_etf,
        "kind": member.kind,
        "indexes": member.indexes,
        "price": round(price, 2),
        "change_pct": round((price / prev_close - 1) * 100, 2) if prev_close else 0.0,
        "avg_dollar_volume": adv,
        "atr_pct": round(atr_pct, 2),
        "as_of": daily.index[-1].strftime("%Y-%m-%d"),
        "score": sc.score,
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
    rows = []
    for m in members:
        row = scan_symbol(m, daily_by_symbol.get(m.symbol))
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
