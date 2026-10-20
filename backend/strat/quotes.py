"""Premarket and after-hours prices for the index cards.

Daily history ends at the last regular session, so a change computed from it before the
open is the prior session's move (Monday's rally, on a Tuesday morning) rather than the
live print versus that session's close. These quotes are fetched once for the index
symbols, cached, and overlaid on the market cards. They are not written into the daily bars.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping, Optional, Sequence

import pandas as pd

from . import config, data
from .scheduler import AFTER_HOURS_END, CLOSE, ET, OPEN, PREMARKET_AT, now_et, session_phase

log = logging.getLogger(__name__)


def percent_change(price: float, prior: float) -> float:
    """Percent change of ``price`` versus ``prior``, rounded to 2 decimals.

    ``0`` when there is no prior close. This is the regular-session day change
    (last bar versus the bar before it) and the extended-hours change (live print
    versus the prior regular close).
    """
    if not prior:
        return 0.0
    return round((float(price) / float(prior) - 1) * 100, 2)


@dataclass(frozen=True)
class IndexQuote:
    symbol: str
    price: float
    previous_close: float
    change_pct: float
    session: str  # "premarket" | "after_hours"
    day: str
    as_of: str


def index_symbols() -> list[str]:
    from .universe import MARKET_ETFS

    return [e[0] for e in MARKET_ETFS]


def reference_close(daily: pd.DataFrame | None, phase: str, now: datetime) -> Optional[float]:
    """The regular-session close the extended move is measured against.

    Premarket uses the last bar before today's Eastern date (yesterday's close, not the
    close before that). After hours uses today's regular close. A bar dated today is
    not the premarket baseline, even if a partial bar was stored early.
    """
    if daily is None or daily.empty or phase not in ("premarket", "after_hours"):
        return None
    today = pd.Timestamp(now_et(now).date())
    days = _naive_days(daily.index)
    if phase == "premarket":
        prior = daily[days < today]
    else:
        prior = daily[days == today]
    if prior.empty:
        return None
    close = float(prior["close"].iloc[-1])
    return close if close > 0 else None


def build_index_quotes(
    prices: Mapping[str, float],
    daily_by_symbol: Mapping[str, pd.DataFrame] | None,
    now: datetime,
    phase: str,
) -> list[dict]:
    """Quote rows for the symbols that have both a live print and a reference close."""
    if phase not in ("premarket", "after_hours") or not prices:
        return []
    local = now_et(now)
    day = local.date().isoformat()
    as_of = local.isoformat(timespec="seconds")
    rows = []
    for sym, raw in prices.items():
        if raw is None:
            continue
        daily = _daily_for(sym, daily_by_symbol)
        prior = reference_close(daily, phase, local)
        if prior is None:
            continue
        price = round(float(raw), 2)
        prior_r = round(float(prior), 2)
        if price <= 0 or prior_r <= 0:
            continue
        rows.append(
            {
                "symbol": sym,
                "price": price,
                "previous_close": prior_r,
                "change_pct": percent_change(price, prior_r),
                "session": phase,
                "day": day,
                "as_of": as_of,
            }
        )
    return rows


def active_quotes(now: datetime | None = None) -> dict[str, IndexQuote]:
    """Cached quotes for the current extended session, or nothing once the session has moved on.

    A cut-off view (``STRAT_AS_OF``) keeps the historical daily change and never overlays a live print.
    """
    if config.AS_OF:
        return {}
    local = now_et(now)
    phase = session_phase(local)
    if phase not in ("premarket", "after_hours"):
        return {}
    day = local.date().isoformat()
    out = {}
    for row in data.load_index_quotes():
        if row["session"] == phase and row["day"] == day:
            out[row["symbol"]] = IndexQuote(**row)
    return out


def fetch_extended_prices(symbols: Sequence[str] | None = None, now: datetime | None = None) -> dict[str, float]:
    """Latest premarket or after-hours print per symbol. Empty outside those sessions or when Yahoo fails."""
    local = now_et(now)
    phase = session_phase(local)
    if phase not in ("premarket", "after_hours"):
        return {}
    symbols = list(symbols or index_symbols())
    if not symbols:
        return {}
    try:
        from .provider import get_provider

        fetch = getattr(get_provider(), "fetch_prepost", None)
        frame = fetch(symbols) if fetch else None
    except Exception:
        log.warning("index prepost fetch failed", exc_info=True)
        return {}
    return last_extended_prices(frame, symbols, local, phase)


def last_extended_prices(
    frame: pd.DataFrame | None, symbols: Sequence[str], now: datetime, phase: str
) -> dict[str, float]:
    """Last 1-minute close inside today's extended window. Bars from another session are ignored."""
    if frame is None or frame.empty or phase not in ("premarket", "after_hours"):
        return {}
    today = now_et(now).date()
    out: dict[str, float] = {}
    for sym in symbols:
        series = _close_series(frame, sym, symbols).dropna()
        if series.empty:
            continue
        series = series.copy()
        series.index = _to_et(series.index)
        series = series[series.index.map(lambda ts: _bar_in_phase(ts, phase, today))]
        if series.empty:
            continue
        price = float(series.iloc[-1])
        if price > 0:
            out[sym] = price
    return out


def _daily_for(symbol: str, daily_by_symbol: Mapping[str, pd.DataFrame] | None) -> pd.DataFrame:
    df = daily_by_symbol.get(symbol) if daily_by_symbol else None
    if df is None or df.empty:
        df = data.load_daily(symbol)
    return df


def _naive_days(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert(ET).tz_localize(None)
    return idx.normalize()


def _to_et(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if idx.tz is None:
        return idx.tz_localize(ET)
    return idx.tz_convert(ET)


def _bar_in_phase(ts: pd.Timestamp, phase: str, today: date) -> bool:
    local = ts.tz_convert(ET) if ts.tzinfo else ts.tz_localize(ET)
    if local.date() != today:
        return False
    t = local.time().replace(microsecond=0)
    # Truncating microseconds keeps a 09:29:59.9 bar inside premarket and a 20:00 bar out.
    if phase == "premarket":
        return PREMARKET_AT <= t < OPEN
    if phase == "after_hours":
        return CLOSE <= t < AFTER_HOURS_END
    return False


def _close_series(frame: pd.DataFrame, symbol: str, symbols: Sequence[str]) -> pd.Series:
    cols = frame.columns
    if isinstance(cols, pd.MultiIndex):
        level0 = set(cols.get_level_values(0))
        level1 = set(cols.get_level_values(1))
        if symbol in level0:
            sub = frame[symbol]
        elif symbol in level1:
            sub = frame.xs(symbol, axis=1, level=1)
        else:
            return pd.Series(dtype=float)
    else:
        # A flat frame is a single-ticker download. Don't reuse it for every symbol.
        if len(symbols) != 1 or symbols[0] != symbol:
            return pd.Series(dtype=float)
        sub = frame
    if isinstance(sub, pd.Series):
        return sub
    for name in ("Close", "close"):
        if name in sub.columns:
            return sub[name]
    return pd.Series(dtype=float)
