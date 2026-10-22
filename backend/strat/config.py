"""Runtime settings. Every value can be overridden with an environment variable."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
CACHE_DB = Path(os.environ.get("STRAT_CACHE_DB", DATA_DIR / "cache.sqlite3"))

MIN_PRICE = float(os.environ.get("STRAT_MIN_PRICE", "10"))
MIN_DOLLAR_VOLUME = float(os.environ.get("STRAT_MIN_DOLLAR_VOLUME", "50000000"))
ADV_LOOKBACK_DAYS = int(os.environ.get("STRAT_ADV_LOOKBACK_DAYS", "20"))

HISTORY_PERIOD = os.environ.get("STRAT_HISTORY_PERIOD", "3y")
INCREMENTAL_PERIOD = os.environ.get("STRAT_INCREMENTAL_PERIOD", "3mo")
DOWNLOAD_BATCH = int(os.environ.get("STRAT_DOWNLOAD_BATCH", "80"))
POLL_SECONDS = int(os.environ.get("STRAT_POLL_SECONDS", "900"))
# Alpaca: today's session is polled on these marks (5-minute bars), this many seconds after each one.
LIVE_POLL_MINUTES = int(os.environ.get("STRAT_LIVE_POLL_MINUTES", "5"))
LIVE_POLL_OFFSET_SECONDS = int(os.environ.get("STRAT_LIVE_POLL_OFFSET_SECONDS", "10"))
# Live trigger breaks read IEX prices, which can differ from the consolidated tape by a few cents.
# During the regular session a pending trigger only counts as broken by today's bar when today's high
# clears it by more than this many dollars. Completed bars (SIP) never use it.
LIVE_TRIGGER_TOLERANCE = float(os.environ.get("STRAT_LIVE_TRIGGER_TOLERANCE", "0.05"))


def scheduler_enabled() -> bool:
    """Background fetcher. Tests set STRAT_SCHEDULER=0 so importing the API does not call Yahoo."""
    return os.environ.get("STRAT_SCHEDULER", "1").strip().lower() not in ("0", "false", "no")

# Cut the cached history off at this date (YYYY-MM-DD) to see the scanner as it would have looked then.
AS_OF = os.environ.get("STRAT_AS_OF") or None
