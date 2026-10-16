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
