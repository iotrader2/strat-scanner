"""The effective scan universe: S&P 500 / Nasdaq-100 / ETFs plus off-universe symbols on the watchlist."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from . import data, earnings
from .universe import Member, load_universe

log = logging.getLogger(__name__)


def extra_members(only_watched: bool, base: Optional[list[Member]] = None) -> list[Member]:
    """Symbols added from the watchlist that are not in the universe (only the watched ones by default)."""
    known = {m.symbol for m in (load_universe() if base is None else base)}
    watched = set(data.watchlist()) if only_watched else None
    return [
        Member(e["symbol"], e["name"], e["sector"], e["kind"], "Watchlist", in_universe=False)
        for e in data.extra_symbols()
        if e["symbol"] not in known and (watched is None or e["symbol"] in watched)
    ]


def effective_universe(base: Optional[list[Member]] = None) -> list[Member]:
    """Universe plus watched off-universe symbols, which are scanned and refreshed like the rest."""
    base = load_universe() if base is None else base
    return base + extra_members(only_watched=True, base=base)


def refresh_earnings(
    members: list[Member], max_age_hours: float, progress: Callable[[int, int, str], None] | None = None
) -> None:
    """Earnings dates for the stocks among ``members``; failures are logged, never raised."""
    try:
        earnings.refresh_earnings(
            [m.symbol for m in members if m.kind == "stock"], max_age_hours=max_age_hours, progress=progress
        )
    except Exception:
        log.exception("earnings refresh failed")
