"""Underlying stock → single-stock inverse ETF for short-side alerts.

Short exposure is taken by longing the mapped inverse ETF (never shorting the underlying).
Edit this dict to add or change pairs. Underlyings with no mapping produce no short alert.
"""

from __future__ import annotations

from typing import Optional

# underlying -> inverse ETF ticker
INVERSE_ETF_MAP: dict[str, str] = {
    "NFLX": "NFXS",
    "PLTR": "PLTD",
    "MSFT": "MSFD",
    "AAPL": "AAPD",
    "META": "METD",
    "NVDA": "NVDD",
    "AMZN": "AMZD",
    "TSLA": "TSLS",
    "TSM": "TSMZ",
    "AMD": "AMDD",
    "GOOGL": "GGLS",
    "MU": "MUD",
    # Mostly -2x (Defiance and others). The alert runs on the ETF's own 15-minute bars, so the stop and
    # R are in the ETF's price; size these smaller than a 1x pair.
    "MSTR": "SMST",
    "SMCI": "SMCZ",
    "RGTI": "RGTZ",
    "IONQ": "IONZ",
    "RKLB": "RKLZ",
    "BMNR": "BMNZ",
    "ASTS": "ASTN",
    "QBTS": "QBTZ",
    "SPCX": "SPCQ",
    "COIN": "CONI",
}

# Inverse ETF -> underlying (built once)
UNDERLYING_FOR_ETF: dict[str, str] = {etf: und for und, etf in INVERSE_ETF_MAP.items()}


def inverse_etf_for(symbol: str) -> Optional[str]:
    """Mapped inverse ETF for ``symbol``, or None when there is no pair."""
    return INVERSE_ETF_MAP.get(str(symbol).upper())


def underlying_for_etf(symbol: str) -> Optional[str]:
    """Underlying for an inverse ETF ticker, or None."""
    return UNDERLYING_FOR_ETF.get(str(symbol).upper())


def map_underlyings_to_etfs(symbols: list[str]) -> list[tuple[str, str]]:
    """``(etf, underlying)`` pairs for symbols that have a mapping, preserving order and uniqueness."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for sym in symbols:
        etf = inverse_etf_for(sym)
        if not etf or etf in seen:
            continue
        seen.add(etf)
        out.append((etf, str(sym).upper()))
    return out
