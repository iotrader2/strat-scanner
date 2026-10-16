"""Trend call for QQQ, SPY and IWM versus their 10, 20 and 50 day averages."""

from __future__ import annotations

from typing import Optional

import pandas as pd

SYMBOLS = ("QQQ", "SPY", "IWM")
PERIODS = (10, 20, 50)


def _sma(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def index_trend(daily_by_symbol: dict[str, pd.DataFrame]) -> Optional[dict]:
    """``on`` when every index is above all three averages, ``off`` when every index is below all three, else ``caution``.

    Returns None when any index is missing the 50 days needed for the longest average.
    """
    indexes = []
    for symbol in SYMBOLS:
        daily = daily_by_symbol.get(symbol)
        if daily is None or daily.empty or "close" not in daily:
            return None
        closes = [float(c) for c in daily["close"].tolist()]
        price = closes[-1]
        averages = []
        for period in PERIODS:
            value = _sma(closes, period)
            if value is None:
                return None
            averages.append({"period": period, "value": value, "above": price > value})
        indexes.append({"symbol": symbol, "price": price, "averages": averages})

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
    return {"call": call, "indexes": indexes}
