"""Local HTTP API consumed by the web UI (bound to 127.0.0.1 only)."""

from __future__ import annotations

import logging
import re
import threading
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import config, data, earnings
from .scanner import chart_payload, scan_all, scan_symbol, sector_entries
from .members import effective_universe, extra_members, refresh_earnings
from .universe import ETFS, SECTOR_ETF, Member, load_universe, to_yahoo

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


def _universe() -> list[Member]:
    return effective_universe(load_universe())


def _find_member(symbol: str) -> Optional[Member]:
    """Universe member, or any symbol ever added from the watchlist (so its detail page keeps working)."""
    base = load_universe()
    return next((m for m in base + extra_members(only_watched=False, base=base) if m.symbol == symbol), None)


def _rescan_symbol(member: Member) -> None:
    daily = data.load_daily(member.symbol)
    State.daily = {**State.daily, member.symbol: daily}
    row = scan_symbol(member, daily)
    rows = [r for r in State.scan if r["symbol"] != member.symbol] + ([row] if row else [])
    State.scan = sorted(rows, key=lambda r: r["score"], reverse=True)


def _run_refresh(full: bool) -> None:
    try:
        symbols = [m.symbol for m in _universe()]

        def progress(done: int, total: int, message: str) -> None:
            State.progress = {"done": done, "total": total, "message": message}

        data.refresh(symbols, full=full, progress=progress)
        _refresh_earnings(max_age_hours=0, progress=progress)
        State.error = None
    except Exception as exc:
        log.exception("refresh failed")
        State.error = str(exc)
    finally:
        State.refreshing = False
        _ensure_scan(force=True)


def _refresh_earnings(max_age_hours: float, progress=None) -> None:
    refresh_earnings(_universe(), max_age_hours, progress)


def _with_earnings(rows: list[dict]) -> list[dict]:
    """Attach the upcoming-earnings warning (next 10 calendar days, as of today) to each row."""
    cached = data.load_earnings()
    today = earnings.today_et()
    return [
        {**r, "earnings": earnings.upcoming(cached.get(r["symbol"]), today) if r.get("kind") == "stock" else None}
        for r in rows
    ]


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
    else:
        threading.Thread(target=_refresh_earnings, kwargs={"max_age_hours": earnings.MAX_AGE_HOURS}, daemon=True).start()


@app.get("/api/status")
def status():
    universe = {m.symbol for m in _universe()}
    return {
        "last_refresh": data.get_meta("last_refresh"),
        "refreshing": State.refreshing,
        "progress": State.progress,
        "error": State.error,
        "symbols_cached": len(universe & set(data.cached_symbols())),
        "universe_size": len(universe),
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
    rows = _with_earnings([
        {k: v for k, v in r.items() if k != "setups"}
        for r in _ensure_scan()
        if r["has_setup"]
        and r["price"] >= min_price
        and r["avg_dollar_volume"] >= min_dollar_volume
        and (include_etfs or r["kind"] == "stock")
    ])
    return {"as_of": State.scan_key, "count": len(rows), "rows": rows}


@app.get("/api/symbol/{symbol}")
def symbol_detail(symbol: str):
    symbol = symbol.upper()
    _ensure_scan()
    member = _find_member(symbol)
    daily = State.daily.get(symbol)
    if member is None or daily is None or daily.empty:
        raise HTTPException(404, f"{symbol} is not in the cache")
    row = next((r for r in State.scan if r["symbol"] == symbol), None) or scan_symbol(member, daily)
    if row is None:
        raise HTTPException(404, f"{symbol} does not have enough price history yet")
    return {
        "row": _with_earnings([row])[0],
        "charts": {tf: chart_payload(daily, tf, CHART_LIMITS[tf]) for tf in CHART_LIMITS},
    }


class WatchRequest(BaseModel):
    symbol: str


def _watchlist_payload() -> dict:
    symbols = data.watchlist()
    by_symbol = {r["symbol"]: r for r in _ensure_scan()}
    return {
        "symbols": symbols,
        "rows": _with_earnings([by_symbol[s] for s in symbols if s in by_symbol]),
        "missing": [s for s in symbols if s not in by_symbol],
    }


@app.get("/api/watchlist")
def get_watchlist():
    """Watched names with their full scan row, whether or not they still have a weekly setup."""
    return _watchlist_payload()


TICKER_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-=]{0,14}$")


@app.post("/api/watchlist")
def add_watch(req: WatchRequest):
    """Add any ticker. Symbols outside the universe are validated and downloaded via yfinance first."""
    raw = req.symbol.strip().upper()
    if not TICKER_RE.match(raw):
        raise HTTPException(404, f"{raw or 'Empty symbol'} is not a valid ticker")
    universe = {m.symbol for m in load_universe()}
    symbol = to_yahoo(raw) if to_yahoo(raw) in universe else raw
    if symbol in data.watchlist():
        return _watchlist_payload()
    if symbol not in universe:
        try:
            bars, meta = data.lookup_symbol(symbol)
        except data.SymbolNotFound:
            raise HTTPException(404, f"{symbol} was not found on Yahoo Finance")
        except data.LookupFailed as exc:
            raise HTTPException(502, f"Could not look up {symbol} right now: {exc}")
        data.save_bars(symbol, bars)
        data.save_extra_symbol(symbol, meta["name"], meta["sector"], meta["kind"])
        if meta["kind"] == "stock":
            earnings.refresh_earnings([symbol], max_age_hours=0)
        data.add_to_watchlist(symbol)
        _ensure_scan()
        _rescan_symbol(_find_member(symbol))
    else:
        data.add_to_watchlist(symbol)
    return _watchlist_payload()


@app.delete("/api/watchlist/{symbol}")
def remove_watch(symbol: str):
    symbol = symbol.strip().upper()
    data.remove_from_watchlist(symbol)
    if symbol not in {m.symbol for m in load_universe()}:
        State.scan = [r for r in State.scan if r["symbol"] != symbol]
    return _watchlist_payload()


@app.get("/api/sectors")
def sectors(tf: str = Query("D", pattern="^[MWD]$"), bars: int = Query(60, ge=10, le=300)):
    _ensure_scan()
    by_symbol = {r["symbol"]: r for r in State.scan}
    out = sector_entries(ETFS, by_symbol, State.daily, tf, bars)
    return {"tf": tf, "as_of": State.scan_key, "etfs": out}
