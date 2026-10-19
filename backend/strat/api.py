"""Local HTTP API consumed by the web UI (bound to 127.0.0.1 only)."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from . import config, data, earnings
from .hub import hub
from .scheduler import decide, fetch_period, now_et
from .breadth import fetch_breadth
from .trend import index_trend
from .members import backfill_industries, effective_universe, extra_members, refresh_earnings
from .leadership import LEADER_MIN_RS, is_leader
from .perf import MomentumRanks, Perf
from .scanner import ScanResult, chart_payload, etf_cards, scan_all, scan_symbol, theme_cards
from .themes import ThemeError, ThemeMap, load_themes
from .universe import MARKET_ETFS, Member, load_universe, to_yahoo

log = logging.getLogger(__name__)
app = FastAPI(title="TiltKiller (local)")

CHART_LIMITS = {"M": 60, "W": 156, "D": 260}


class State:
    lock = threading.Lock()
    refreshing = False
    progress = {"done": 0, "total": 0, "message": ""}
    error: Optional[str] = None
    scan: list[dict] = []
    scan_key: Optional[str] = None
    daily: dict = {}
    result: Optional[ScanResult] = None
    strengths: dict = {}
    ranks: MomentumRanks = MomentumRanks({})
    qqq: dict[str, Optional[float]] = {}
    prior: dict = {}
    theme_map: Optional[ThemeMap] = None
    version: int = 0


def _universe() -> list[Member]:
    return effective_universe(load_universe())


def _find_member(symbol: str) -> Optional[Member]:
    """Universe member, or any symbol ever added from the watchlist (so its detail page keeps working)."""
    base = load_universe()
    return next((m for m in base + extra_members(only_tracked=False, base=base) if m.symbol == symbol), None)


def _load_theme_map() -> Optional[ThemeMap]:
    try:
        return load_themes()
    except (OSError, ThemeError):
        log.exception("could not load data/themes.yaml; scanning without themes")
        return None


def _scan_one(member: Member, daily) -> Optional[dict]:
    """Scan one symbol against the current theme ranking and momentum distributions."""
    return scan_symbol(member, daily, State.strengths, State.ranks, State.theme_map, State.qqq, prior=State.prior)


def _rescan_symbol(member: Member) -> None:
    daily = data.load_daily(member.symbol)
    State.daily = {**State.daily, member.symbol: daily}
    row = _scan_one(member, daily)
    rows = [r for r in State.scan if r["symbol"] != member.symbol] + ([row] if row else [])
    State.scan = sorted(rows, key=lambda r: r["score"], reverse=True)


def _run_refresh(full: bool, period: str | None = None, with_earnings: bool = True) -> None:
    try:
        symbols = [m.symbol for m in _universe()]

        def progress(done: int, total: int, message: str) -> None:
            State.progress = {"done": done, "total": total, "message": message}
            _publish_status()

        data.refresh(symbols, full=full, progress=progress, period=period)
        if with_earnings:
            backfill_industries(_universe())
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
    today = date.fromisoformat(config.AS_OF) if config.AS_OF else earnings.today_et()
    return [
        {**r, "earnings": earnings.upcoming(cached.get(r["symbol"]), today) if r.get("kind") == "stock" else None}
        for r in rows
    ]


def _publish_status() -> None:
    hub.publish({"type": "status", "version": State.version, "status": _status_body()})


def start_refresh(full: bool = False, period: str | None = None, with_earnings: bool = True) -> bool:
    with State.lock:
        if State.refreshing:
            return False
        State.refreshing = True
        State.error = None
        State.progress = {"done": 0, "total": 0, "message": "Starting"}
    _publish_status()
    threading.Thread(target=_run_refresh, args=(full, period, with_earnings), daemon=True).start()
    return True


def _row_sig(row: dict) -> tuple:
    return (
        row.get("price"),
        row.get("score"),
        row.get("change_pct"),
        row.get("leader_status"),
        row.get("setup"),
        row.get("rs"),
    )


def _wire_message(kind: str, previous: Optional[list[dict]] = None) -> dict:
    rows = State.scan
    removed: list[str] = []
    changed = rows
    if kind == "delta" and previous is not None:
        prev = {r["symbol"]: r for r in previous}
        changed = [r for r in rows if _row_sig(prev.get(r["symbol"], {})) != _row_sig(r)]
        removed = [s for s in prev if s not in {r["symbol"] for r in rows}]
        if len(changed) > max(40, len(rows) // 2):
            kind, changed, removed = "snapshot", rows, []
    return {
        "type": kind,
        "version": State.version,
        "computed_at": State.scan_key,
        "status": _status_body(),
        "changed": changed,
        "removed": removed,
    }


def _ensure_scan(force: bool = False) -> list[dict]:
    key = data.get_meta("last_refresh")
    if not force and key == State.scan_key and State.scan and State.result is not None:
        return State.scan
    if not force and key == State.scan_key and State.scan:
        return State.scan
    previous = list(State.scan)
    daily = data.load_all_daily()
    State.daily = daily
    State.theme_map = _load_theme_map()
    result = scan_all(_universe(), daily, State.theme_map)
    State.result, State.scan = result, result.rows
    State.strengths, State.ranks, State.qqq, State.prior = result.strengths, result.ranks, result.qqq, result.prior
    State.scan_key = key
    State.version += 1
    data.save_snapshot(State.version, key or "", State.scan)
    hub.publish(_wire_message("delta" if previous else "snapshot", previous))
    return State.scan


def _ensure_charts() -> None:
    """Chart routes need the full scan. The table can render from the saved snapshot before that finishes."""
    if State.result is not None and State.daily:
        return
    _ensure_scan(force=True)


def _hydrate() -> None:
    snap = data.load_snapshot()
    if not snap:
        return
    State.scan = snap["rows"]
    State.scan_key = snap["computed_at"]
    State.version = snap["version"]


def _boot() -> None:
    if config.AS_OF:
        _ensure_scan(force=True)
        return
    if not data.cached_symbols():
        log.info("Cache is empty, starting the initial download")
        start_refresh(full=True)
        return
    threading.Thread(target=_refresh_earnings, kwargs={"max_age_hours": earnings.MAX_AGE_HOURS}, daemon=True).start()
    _ensure_scan(force=True)
    _scheduler_loop()


def _scheduler_loop() -> None:
    last_poll = None
    while True:
        time.sleep(20)
        if config.AS_OF or State.refreshing:
            continue
        now = now_et()
        kind = decide(now, data.newest_bar_date(), last_poll)
        if kind is None:
            continue
        if kind == "intraday":
            last_poll = now
            start_refresh(full=False, period="5d", with_earnings=False)
        else:
            newest = data.newest_bar_date()
            window = fetch_period(now, newest)
            start_refresh(full=window == config.HISTORY_PERIOD, period=None if window == config.HISTORY_PERIOD else window)


@app.on_event("startup")
async def _startup() -> None:
    hub.attach(asyncio.get_running_loop())
    asyncio.create_task(hub.heartbeat())
    _hydrate()
    if config.scheduler_enabled():
        threading.Thread(target=_boot, daemon=True).start()


def _status_body() -> dict:
    universe = {m.symbol for m in _universe()}
    return {
        "last_refresh": data.get_meta("last_refresh"),
        "as_of": config.AS_OF,
        "refreshing": State.refreshing,
        "updating": State.refreshing,
        "progress": State.progress,
        "error": State.error,
        "symbols_cached": len(universe & set(data.cached_symbols())),
        "universe_size": len(universe),
        "version": State.version,
        "computed_at": State.scan_key,
        "delay": "15m",
    }


@app.get("/api/status")
def status():
    return _status_body()


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    """Snapshot on connect, then deltas. Heartbeats keep the socket inside a host's idle timeout."""
    await websocket.accept()
    hub.add(websocket)
    try:
        await websocket.send_json(_wire_message("snapshot"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.discard(websocket)


@app.post("/api/refresh")
def refresh(full: bool = False):
    """Operator hook. The UI does not call this; the scheduler does."""
    return {"started": start_refresh(full=full)}


@app.get("/api/config")
def get_config():
    return {
        "min_price": config.MIN_PRICE,
        "min_dollar_volume": config.MIN_DOLLAR_VOLUME,
        "leader_min_rs": LEADER_MIN_RS,
        "themes": [
            {"id": t.id, "name": t.name, "count": len(t.everyone)}
            for t in sorted((State.theme_map or _load_theme_map() or ThemeMap(0, [])).themes, key=lambda t: t.name)
        ],
    }


@app.get("/api/scan")
def scan(
    min_price: float = Query(None),
    min_dollar_volume: float = Query(None),
    include_etfs: bool = True,
    leaders_only: bool = True,
    min_rs: float = Query(None, ge=0, le=1),
):
    """Ranked scan rows. By default only leaders: relative strength at or above ``min_rs`` (a 0..1 percentile,
    default P90) with the trend intact. A weekly setup is not required; names without one are labelled in the row."""
    min_price = config.MIN_PRICE if min_price is None else min_price
    min_dollar_volume = config.MIN_DOLLAR_VOLUME if min_dollar_volume is None else min_dollar_volume
    cut = LEADER_MIN_RS if min_rs is None else min_rs
    rows = _with_earnings([
        {k: v for k, v in r.items() if k != "setups"}
        for r in _ensure_scan()
        if r["price"] >= min_price
        and r["avg_dollar_volume"] >= min_dollar_volume
        and (include_etfs or r["kind"] == "stock")
        and (not leaders_only or is_leader(r["rs"], r["leadership"]["breakdown"], cut))
    ])
    return {"as_of": State.scan_key, "count": len(rows), "rows": rows}


@app.get("/api/symbol/{symbol}")
def symbol_detail(symbol: str):
    symbol = symbol.upper()
    _ensure_charts()
    member = _find_member(symbol)
    daily = State.daily.get(symbol)
    if member is None or daily is None or daily.empty:
        raise HTTPException(404, f"{symbol} is not in the cache")
    row = next((r for r in State.scan if r["symbol"] == symbol), None) or _scan_one(member, daily)
    if row is None:
        raise HTTPException(404, f"{symbol} does not have enough price history yet")
    return {
        "row": _with_earnings([row])[0],
        "charts": {tf: chart_payload(daily, tf, CHART_LIMITS[tf]) for tf in CHART_LIMITS},
    }


class WatchRequest(BaseModel):
    symbol: str


class PositionRequest(BaseModel):
    symbol: str
    entry_price: Optional[float] = Field(None, gt=0)
    shares: Optional[float] = Field(None, gt=0)
    entry_date: Optional[date] = None


class PositionUpdate(BaseModel):
    entry_price: float = Field(gt=0)
    shares: Optional[float] = Field(None, gt=0)
    entry_date: date


TICKER_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-=]{0,14}$")


def _rows_by_symbol() -> dict[str, dict]:
    return {r["symbol"]: r for r in _ensure_scan()}


def _resolve_symbol(raw: str) -> tuple[str, bool]:
    """Canonical symbol and whether it is in the scan universe ("brk.b" -> "BRK-B"); 404 if malformed."""
    raw = raw.strip().upper()
    if not TICKER_RE.match(raw):
        raise HTTPException(404, f"{raw or 'Empty symbol'} is not a valid ticker")
    universe = {m.symbol for m in load_universe()}
    if to_yahoo(raw) in universe:
        return to_yahoo(raw), True
    return raw, raw in universe


def _fetch_off_universe(symbol: str) -> None:
    """Validate an off-universe ticker via yfinance and cache its bars, metadata and earnings."""
    try:
        bars, meta = data.lookup_symbol(symbol)
    except data.SymbolNotFound:
        raise HTTPException(404, f"{symbol} was not found on Yahoo Finance")
    except data.LookupFailed as exc:
        raise HTTPException(502, f"Could not look up {symbol} right now: {exc}")
    from .provider import splits_in

    data.save_splits(symbol, splits_in(bars))
    data.save_bars(symbol, bars)
    data.save_extra_symbol(symbol, meta["name"], meta["sector"], meta["kind"], meta.get("industry", ""))
    if meta["kind"] == "stock":
        earnings.refresh_earnings([symbol], max_age_hours=0)


def _start_tracking(symbol: str, in_universe: bool) -> None:
    """Make sure an off-universe symbol that was just watched or bought is scanned (call after saving it)."""
    if not in_universe:
        _ensure_scan()
        _rescan_symbol(_find_member(symbol))


def _stop_tracking_if_unused(symbol: str) -> None:
    """Drop an off-universe symbol from the scan once it is neither watched nor held."""
    if symbol not in {m.symbol for m in load_universe()} and symbol not in data.tracked_symbols():
        State.scan = [r for r in State.scan if r["symbol"] != symbol]


def _watchlist_payload() -> dict:
    symbols = data.watchlist()
    by_symbol = _rows_by_symbol()
    return {
        "symbols": symbols,
        "rows": _with_earnings([by_symbol[s] for s in symbols if s in by_symbol]),
        "missing": [s for s in symbols if s not in by_symbol],
    }


@app.get("/api/watchlist")
def get_watchlist():
    """Watched names with their full scan row, whether or not they still have a weekly setup."""
    return _watchlist_payload()


@app.post("/api/watchlist")
def add_watch(req: WatchRequest):
    """Add any ticker. Symbols outside the universe are validated and downloaded via yfinance first."""
    symbol, in_universe = _resolve_symbol(req.symbol)
    if symbol in data.watchlist():
        return _watchlist_payload()
    if not in_universe and symbol not in data.tracked_symbols():
        _fetch_off_universe(symbol)
    data.add_to_watchlist(symbol)
    _start_tracking(symbol, in_universe)
    return _watchlist_payload()


@app.delete("/api/watchlist/{symbol}")
def remove_watch(symbol: str):
    symbol = symbol.strip().upper()
    data.remove_from_watchlist(symbol)
    _stop_tracking_if_unused(symbol)
    return _watchlist_payload()


def _positions_payload() -> dict:
    held = data.positions()
    held_symbols = {p["symbol"] for p in held}
    rows = {r["symbol"]: r for r in _with_earnings([r for r in _rows_by_symbol().values() if r["symbol"] in held_symbols])}
    return {
        "symbols": [p["symbol"] for p in held],
        "positions": [{**p, "row": rows.get(p["symbol"])} for p in held],
    }


def _check_entry_date(d: date) -> str:
    if d > earnings.today_et():
        raise HTTPException(422, "Entry date cannot be in the future")
    return d.isoformat()


@app.get("/api/positions")
def get_positions():
    """Open positions with their entry details and live scan row (row is null until data is cached)."""
    return _positions_payload()


@app.post("/api/positions")
def add_position(req: PositionRequest):
    """Open a position in any ticker (moving it off the watchlist). Entry defaults: last price, today."""
    symbol, in_universe = _resolve_symbol(req.symbol)
    if any(p["symbol"] == symbol for p in data.positions()):
        raise HTTPException(409, f"{symbol} is already in Positions")
    entry_date = _check_entry_date(req.entry_date or earnings.today_et())
    if not in_universe and symbol not in data.tracked_symbols():
        _fetch_off_universe(symbol)
    entry_price = req.entry_price
    if entry_price is None:
        member = _find_member(symbol)
        daily = data.load_daily(symbol) if member else None
        row = _rows_by_symbol().get(symbol) or (_scan_one(member, daily) if member else None)
        if row is None:
            raise HTTPException(422, f"No price for {symbol} yet; enter an entry price")
        entry_price = row["price"]
    data.save_position(symbol, entry_price, req.shares, entry_date)
    data.remove_from_watchlist(symbol)
    _start_tracking(symbol, in_universe)
    return _positions_payload()


@app.put("/api/positions/{symbol}")
def update_position(symbol: str, req: PositionUpdate):
    symbol = symbol.strip().upper()
    if not any(p["symbol"] == symbol for p in data.positions()):
        raise HTTPException(404, f"{symbol} is not in Positions")
    data.save_position(symbol, req.entry_price, req.shares, _check_entry_date(req.entry_date))
    return _positions_payload()


@app.delete("/api/positions/{symbol}")
def close_position(symbol: str):
    symbol = symbol.strip().upper()
    data.remove_position(symbol)
    _stop_tracking_if_unused(symbol)
    return _positions_payload()


@app.post("/api/positions/{symbol}/watchlist")
def position_to_watchlist(symbol: str):
    """Move a position back to the watchlist."""
    symbol = symbol.strip().upper()
    if not any(p["symbol"] == symbol for p in data.positions()):
        raise HTTPException(404, f"{symbol} is not in Positions")
    data.add_to_watchlist(symbol)
    data.remove_position(symbol)
    return _positions_payload()


@app.get("/api/themes")
def themes(tf: str = Query("W", pattern="^[MWD]$"), bars: int = Query(60, ge=10, le=300)):
    """Theme cards, strongest first: equal-weight index candles, score row and member chips."""
    _ensure_charts()
    by_symbol = {r["symbol"]: r for r in State.scan}
    result = State.result or ScanResult(State.scan)
    return {"tf": tf, "as_of": State.scan_key, "themes": theme_cards(result, by_symbol, tf, bars)}


@app.get("/api/breadth")
def breadth():
    """$NASI, CNN Fear & Greed and Nasdaq/NYSE advancers vs decliners for State of the Market."""
    return fetch_breadth()


@app.get("/api/market")
def market(tf: str = Query("W", pattern="^(M|W|D|3M|6M)$"), bars: int = Query(60, ge=10, le=300)):
    """State of the Market cards: QQQ, SPY and IWM, in that order."""
    _ensure_charts()
    by_symbol = {r["symbol"]: r for r in State.scan}
    out = etf_cards(MARKET_ETFS, by_symbol, State.daily, tf, bars)
    return {"tf": tf, "as_of": State.scan_key, "etfs": out, "trend": index_trend(State.daily)}
