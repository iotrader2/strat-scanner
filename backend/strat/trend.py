"""Trend call and market score for QQQ, SPY and IWM versus their 6, 20 and 50 day simple averages.

6/20/50 matches the averages drawn on every chart. Like the charts, these are simple (not exponential) averages.
"""

from __future__ import annotations

from typing import Mapping, Optional

import pandas as pd

SYMBOLS = ("QQQ", "SPY", "IWM")
PERIODS = (6, 20, 50)
SCORE_MAX = len(PERIODS) * len(SYMBOLS)


def _sma(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def index_points(price: float, averages: list[float]) -> int:
    """Market-score points for one index: +1 for each average the price is strictly above (0-3 for 6/20/50)."""
    return sum(1 for value in averages if price > value)


def index_trend(daily_by_symbol: dict[str, pd.DataFrame], prices: Optional[Mapping[str, float]] = None) -> Optional[dict]:
    """``on`` when every index is above all three averages, ``off`` when every index is below all three, else ``caution``.

    ``prices`` overrides the last close per symbol with the price the index card shows (a premarket or
    after-hours quote), so the call, the chips and the score agree with the cards. The averages always
    use the regular-session daily closes.

    ``score`` is out of ``SCORE_MAX`` (9): one point per index per average it is above, matching the 6/20/50 chips.

    Returns None when any index is missing the 50 days needed for the longest average.
    """
    indexes = []
    for symbol in SYMBOLS:
        daily = daily_by_symbol.get(symbol)
        if daily is None or daily.empty or "close" not in daily:
            return None
        closes = [float(c) for c in daily["close"].tolist()]
        override = (prices or {}).get(symbol)
        price = float(override) if override is not None else closes[-1]
        averages = []
        for period in PERIODS:
            value = _sma(closes, period)
            if value is None:
                return None
            averages.append({"period": period, "value": value, "above": price > value})
        points = index_points(price, [a["value"] for a in averages])
        indexes.append({"symbol": symbol, "price": price, "averages": averages, "points": points, "max_points": len(PERIODS)})

    if all(all(a["above"] for a in index["averages"]) for index in indexes):
        call = "on"
    elif all(all(index["price"] < a["value"] for a in index["averages"]) for index in indexes):
        call = "off"
    else:
        call = "caution"
    for index in indexes:
        index["price"] = round(index["price"], 2)
        for avg in index["averages"]:
            avg["value"] = round(avg["value"], 2)
    score = sum(index["points"] for index in indexes)
    return {"call": call, "indexes": indexes, "score": score, "score_max": SCORE_MAX}
