"""Local HTTP API consumed by the web UI (bound to 127.0.0.1 only)."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from . import config, data
from .scanner import chart_payload, scan_all, scan_symbol
from .universe import ETFS, SECTOR_ETF, load_universe

log = logging.getLogger(__name__)
app = FastAPI(title="Strat Scanner (local)")

CHART_LIMITS = {"M": 60, "W": 156, "D": 260}


class State:
    lock = threading.Lock()
    refreshing = False
    progress = {"done": 0, "total": 0, "message": ""}
    error: Optional[str] = None
    scan: list[dict] = []
    scan_key: Optional[str] = None
    daily: dict = {}


def _universe():
    return load_universe()


def _run_refresh(full: bool) -> None:
    try:
        symbols = [m.symbol for m in _universe()]

        def progress(done: int, total: int, message: str) -> None:
            State.progress = {"done": done, "total": total, "message": message}

        data.refresh(symbols, full=full, progress=progress)
        State.error = None
    except Exception as exc:
        log.exception("refresh failed")
        State.error = str(exc)
    finally:
        State.refreshing = False
        _ensure_scan(force=True)


def start_refresh(full: bool = False) -> bool:
    with State.lock:
        if State.refreshing:
            return False
        State.refreshing = True
        State.progress = {"done": 0, "total": 0, "message": "Starting"}
    threading.Thread(target=_run_refresh, args=(full,), daemon=True).start()
    return True


def _ensure_scan(force: bool = False) -> list[dict]:
    key = data.get_meta("last_refresh")
    if force or key != State.scan_key or not State.scan:
        daily = data.load_all_daily()
        State.daily = daily
        State.scan = scan_all(_universe(), daily)
        State.scan_key = key
    return State.scan


@app.on_event("startup")
def _startup() -> None:
    if not data.cached_symbols():
        log.info("Cache is empty, starting the initial download")
        start_refresh(full=True)


@app.get("/api/status")
def status():
    return {
        "last_refresh": data.get_meta("last_refresh"),
        "refreshing": State.refreshing,
        "progress": State.progress,
        "error": State.error,
        "symbols_cached": len(data.cached_symbols()),
        "universe_size": len(_universe()),
    }


@app.post("/api/refresh")
def refresh(full: bool = False):
    return {"started": start_refresh(full=full)}


@app.get("/api/config")
def get_config():
    return {
        "min_price": config.MIN_PRICE,
        "min_dollar_volume": config.MIN_DOLLAR_VOLUME,
        "sectors": sorted(SECTOR_ETF),
        "sector_etfs": SECTOR_ETF,
    }


@app.get("/api/scan")
def scan(
    min_price: float = Query(None),
    min_dollar_volume: float = Query(None),
    include_etfs: bool = True,
):
    min_price = config.MIN_PRICE if min_price is None else min_price
    min_dollar_volume = config.MIN_DOLLAR_VOLUME if min_dollar_volume is None else min_dollar_volume
    rows = [
        {k: v for k, v in r.items() if k != "setups"}
        for r in _ensure_scan()
        if r["price"] >= min_price
        and r["avg_dollar_volume"] >= min_dollar_volume
        and (include_etfs or r["kind"] == "stock")
    ]
    return {"as_of": State.scan_key, "count": len(rows), "rows": rows}


@app.get("/api/symbol/{symbol}")
def symbol_detail(symbol: str):
    symbol = symbol.upper()
    _ensure_scan()
    member = next((m for m in _universe() if m.symbol == symbol), None)
    daily = State.daily.get(symbol)
    if member is None or daily is None:
        raise HTTPException(404, f"{symbol} is not in the cached universe")
    return {
        "row": scan_symbol(member, daily),
        "charts": {tf: chart_payload(daily, tf, CHART_LIMITS[tf]) for tf in CHART_LIMITS},
    }


@app.get("/api/sectors")
def sectors(tf: str = Query("D", pattern="^[MWD]$"), bars: int = Query(60, ge=10, le=300)):
    _ensure_scan()
    by_symbol = {r["symbol"]: r for r in State.scan}
    out = []
    for sym, name, sector, group in ETFS:
        daily = State.daily.get(sym)
        row = by_symbol.get(sym)
        if daily is None or row is None:
            continue
        out.append(
            {
                "symbol": sym,
                "name": name,
                "sector": sector,
                "group": group,
                "row": {k: v for k, v in row.items() if k != "setups"},
                "candles": chart_payload(daily, tf, bars),
            }
        )
    return {"tf": tf, "as_of": State.scan_key, "etfs": out}
