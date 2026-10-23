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

from . import config, data, earnings, fetch_worker, logos, memory, quotes, trims
from .hub import hub
from .stage import StageGateMiddleware, configure_logging, mount_ui, use_private_yfinance_cache
from .provider import live_bars_enabled
from .scheduler import decide, fetch_period, now_et, scheduler_sleep, session_phase
from . import breadth as breadth_data
from .breadth import fetch_breadth, universe_breadth
from .trend import index_trend
from .members import backfill_industries, effective_universe, extra_members, refresh_earnings
from .leadership import LEADER_MIN_RS, LEADERS_MIN_SCORE, in_leaders_scan
from .perf import MomentumRanks, Perf
from .scanner import ScanResult, chart_payload, etf_cards, scan_all, scan_symbol, theme_cards
from .themes import ThemeError, ThemeMap, load_themes
from .universe import MARKET_ETFS, Member, load_universe, to_yahoo

configure_logging()
log = logging.getLogger(__name__)
app = FastAPI(title="TiltKiller (local)")
# No-op unless STAGE_TOKEN (secret link) or STAGE_USER/STAGE_PASS are set (Heroku staging).
app.add_middleware(StageGateMiddleware)

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
    quoting: bool = False
    # The one background job allowed at a time ("refresh", "quotes", "earnings"), held from the start of its
    # download until its rescan has finished. Two jobs never download, write the cache or hold a second copy
    # of the universe in memory together.
    job: Optional[str] = None


def _claim_job(kind: str) -> bool:
    """Take the single job slot. False when another download / rescan is still running."""
    with State.lock:
        if State.job is not None or State.refreshing or State.quoting:
            return False
        State.job = kind
        return True


def _release_job() -> None:
    with State.lock:
        State.job = None


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


def _log_rss(phase: str, **fields) -> None:
    """One line per refresh, on stdout even when the root logger is left at WARNING.

    ``STRAT_LOG_LEVEL=info`` records it through the logger. Heroku still shows the
    printed line when that variable is unset.
    """
    detail = " ".join(f"{key}={value}" for key, value in fields.items())
    message = f"refresh {phase} {detail} {memory.format_rss()}".strip()
    log.info(message)
    if not log.isEnabledFor(logging.INFO):
        print(message, flush=True)


def _run_refresh(full: bool, period: str | None = None, with_earnings: bool = True, intraday: bool = False) -> None:
    live = intraday and live_bars_enabled()
    fetch = "child" if fetch_worker.use_child(full, with_earnings) else "in-process"
    _log_rss("start", full=full, period=period or "", earnings=with_earnings, fetch=fetch, **({"kind": "live5m"} if live else {}))
    try:
        symbols = [m.symbol for m in _universe()]

        def progress(done: int, total: int, message: str) -> None:
            State.progress = {"done": done, "total": total, "message": message}
            _publish_status()

        if live:
            from . import intraday as intraday_bars

            stats = intraday_bars.poll(symbols)
            log.info("live 5m poll %s", stats)
        elif fetch == "child":
            fetch_worker.fetch_in_child(full, period, with_earnings, progress)
        else:
            data.refresh(symbols, full=full, progress=progress, period=period)
            if with_earnings:
                backfill_industries(_universe())
                _refresh_earnings(max_age_hours=0, progress=progress)
        State.error = None
    except Exception as exc:
        log.exception("refresh failed")
        State.error = str(exc)
    finally:
        _refresh_nasdaq_issues()
        State.refreshing = False
        try:
            with _scan_lock:
                _ensure_scan(force=True)
        finally:
            memory.release_heap()
            _release_job()
            _log_rss("end", full=full, period=period or "", fetch=fetch)


def _refresh_nasdaq_issues() -> None:
    """Nasdaq advancers / decliners (WSJ diary), inside the refresh's job slot, on the refresh cadence.

    One ~2 KB request. Skipped for a cut-off view and when the background scheduler is off (tests, CLI).
    """
    if config.AS_OF or not config.scheduler_enabled():
        return
    try:
        breadth_data.refresh_nasdaq_issues()
    except Exception:
        log.exception("nasdaq issues refresh failed")


def _warm_earnings(wait_seconds: float = 900, poll: float = 5.0) -> None:
    """Boot-time earnings check, run in the job slot so it never overlaps a price download.

    Waits (up to ``wait_seconds``) for a running job to finish instead of racing it.
    """
    deadline = time.monotonic() + wait_seconds
    while not _claim_job("earnings"):
        if time.monotonic() >= deadline:
            log.warning("earnings warm-up skipped: another fetch held the job slot")
            return
        time.sleep(poll)
    try:
        _refresh_earnings(max_age_hours=earnings.MAX_AGE_HOURS)
    except Exception:
        log.exception("earnings warm-up failed")
    finally:
        # A restart with a warm cache may not refresh prices for hours; read the Nasdaq diary once now.
        _refresh_nasdaq_issues()
        _release_job()


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


def _publish_index_quotes() -> None:
    with _scan_lock:
        State.version += 1
        message = _wire_message("snapshot")
    hub.publish(message)


def _run_index_quotes() -> None:
    """Refresh the index pre/post prints without rescanning the universe."""
    _log_rss("start", fetch="in-process", kind="extended")
    try:
        prices = fetch_worker.extended_prices()
        now = now_et()
        built = quotes.build_index_quotes(prices, State.daily, now, session_phase(now))
        if built and data.save_index_quotes(built):
            _publish_index_quotes()
    except Exception:
        log.exception("index quote refresh failed")
    finally:
        State.quoting = False
        _release_job()
        memory.release_heap()
        _log_rss("end", fetch="in-process", kind="extended")


def start_index_quotes() -> bool:
    with State.lock:
        if State.job is not None or State.refreshing or State.quoting:
            return False
        State.job = "quotes"
        State.quoting = True
    threading.Thread(target=_run_index_quotes, daemon=True).start()
    return True


def start_refresh(
    full: bool = False, period: str | None = None, with_earnings: bool = True, intraday: bool = False
) -> bool:
    with State.lock:
        if State.job is not None or State.refreshing or State.quoting:
            return False
        State.job = "refresh"
        State.refreshing = True
        State.error = None
        State.progress = {"done": 0, "total": 0, "message": "Starting"}
    _publish_status()
    threading.Thread(target=_run_refresh, args=(full, period, with_earnings, intraday), daemon=True).start()
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


_scan_lock = threading.RLock()


def _ensure_scan(force: bool = False) -> list[dict]:
    """Current scan rows, recomputed when the cache changed (or ``force``).

    Request handlers never wait on Yahoo or on another scan: while a fetch is running, or another
    thread is already scanning, they get the rows we have (possibly empty) straight away. The fetcher
    takes ``_scan_lock`` first (it is re-entrant), so its post-refresh scan always runs.
    """
    key = data.get_meta("last_refresh")
    if not force and key == State.scan_key and State.scan:
        return State.scan
    if State.refreshing and not _scan_lock._is_owned():
        return State.scan
    if not _scan_lock.acquire(blocking=False):
        return State.scan
    try:
        return _compute_scan(key)
    finally:
        _scan_lock.release()


def _compute_scan(key: Optional[str]) -> list[dict]:
    previous = list(State.scan)
    # Theme indexes alias the previous price history. Drop them before the reload
    # allocates, and fold new bars into State.daily in batches so the old and new
    # universe are not resident together. Charts keep reading State.daily; a symbol
    # stays on its previous bars until its batch is replaced.
    State.result = None
    data.reload_daily(State.daily)
    memory.release_heap()
    State.theme_map = _load_theme_map()
    result = scan_all(_universe(), State.daily, State.theme_map)
    State.result, State.scan = result, result.rows
    State.strengths, State.ranks, State.qqq, State.prior = result.strengths, result.ranks, result.qqq, result.prior
    State.scan_key = key
    State.version += 1
    data.save_snapshot(State.version, key or "", State.scan)
    hub.publish(_wire_message("delta" if previous else "snapshot", previous))
    memory.release_heap()
    return State.scan


def _ensure_charts() -> None:
    """Chart routes need the full scan. The table can render from the saved snapshot before that finishes."""
    if State.result is not None and State.daily:
        return
    _ensure_scan(force=True)  # returns at once (empty charts) while a fetch or another scan is running


def _hydrate() -> None:
    snap = data.load_snapshot()
    if not snap:
        return
    State.scan = snap["rows"]
    State.scan_key = snap["computed_at"]
    State.version = snap["version"]


def _boot() -> None:
    if config.AS_OF:
        with _scan_lock:
            _ensure_scan(force=True)
        return
    if not data.cached_symbols():
        log.info("Cache is empty, starting the initial download")
        start_refresh(full=True)
    else:
        threading.Thread(target=_warm_earnings, daemon=True).start()
        with _scan_lock:
            _ensure_scan(force=True)
    _scheduler_loop()


def _scheduler_loop() -> None:
    last_poll = None
    last_extended = None
    while True:
        time.sleep(scheduler_sleep(now_et(), live_bars_enabled()))
        if config.AS_OF or State.refreshing or State.quoting or State.job is not None:
            continue
        now = now_et()
        if session_phase(now) not in ("premarket", "after_hours") and data.clear_index_quotes():
            _publish_index_quotes()
        kind = decide(now, data.newest_bar_date(), last_poll, last_extended, aligned=live_bars_enabled())
        if kind is None:
            continue
        if kind == "extended":
            last_extended = now
            start_index_quotes()
        elif kind == "intraday":
            last_poll = now
            start_refresh(full=False, period="5d", with_earnings=False, intraday=True)
        else:
            newest = data.newest_bar_date()
            window = fetch_period(now, newest)
            start_refresh(full=window == config.HISTORY_PERIOD, period=None if window == config.HISTORY_PERIOD else window)


@app.on_event("startup")
async def _startup() -> None:
    use_private_yfinance_cache()
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
        # Alpaca: prices from real-time IEX 5-minute bars (volume trails ~15 min on SIP). Yahoo: ~15-minute delay.
        "delay": "5m" if live_bars_enabled() else "15m",
        "source": "alpaca" if live_bars_enabled() else "yahoo",
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


@app.get("/api/logo/{symbol}")
def logo(symbol: str):
    """Company / fund logo for a ticker (see logos.py): disk-cached, long browser cache; 404 means show the letter avatar."""
    from starlette.responses import FileResponse, Response

    found = logos.get_logo(symbol)
    if found is None:
        return Response(status_code=404, headers={"Cache-Control": logos.MISS_CACHE})
    headers = {"Cache-Control": logos.HIT_CACHE, "X-Content-Type-Options": "nosniff"}
    if found.media_type == "image/svg+xml":
        headers["Content-Security-Policy"] = logos.SVG_CSP
    return FileResponse(found.path, media_type=found.media_type, headers=headers)


@app.get("/api/config")
def get_config():
    return {
        "min_price": config.MIN_PRICE,
        "min_dollar_volume": config.MIN_DOLLAR_VOLUME,
        "leader_min_rs": LEADER_MIN_RS,
        "leaders_min_score": LEADERS_MIN_SCORE,
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
    """Ranked scan rows. By default only the Leaders scan: relative strength at or above ``min_rs`` (a 0..1 percentile,
    default P90) with the trend intact, and a score strictly above ``LEADERS_MIN_SCORE`` (70). A weekly setup is not required; names without one are labelled in the row."""
    min_price = config.MIN_PRICE if min_price is None else min_price
    min_dollar_volume = config.MIN_DOLLAR_VOLUME if min_dollar_volume is None else min_dollar_volume
    cut = LEADER_MIN_RS if min_rs is None else min_rs
    rows = _with_earnings([
        {k: v for k, v in r.items() if k != "setups"}
        for r in _ensure_scan()
        if r["price"] >= min_price
        and r["avg_dollar_volume"] >= min_dollar_volume
        and (include_etfs or r["kind"] == "stock")
        and (not leaders_only or in_leaders_scan(r["rs"], r["leadership"]["breakdown"], r["score"], cut))
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


class TrimRequest(BaseModel):
    shares: float = Field(gt=0)
    price: float = Field(gt=0)


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
    data.save_spinoffs(symbol, bars.attrs.get("spinoffs", []))
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
    by_trim = data.trims_by_symbol()
    held_symbols = {p["symbol"] for p in held}
    rows = {r["symbol"]: r for r in _with_earnings([r for r in _rows_by_symbol().values() if r["symbol"] in held_symbols])}
    return {
        "symbols": [p["symbol"] for p in held],
        "positions": [
            {**trims.annotate(p, by_trim.get(p["symbol"], [])), "row": rows.get(p["symbol"])} for p in held
        ],
    }


def _publish_positions() -> None:
    """Tell open clients to refetch positions. The body stays empty so a 512 MB dyno is not asked to fan out scan rows."""
    hub.publish({"type": "positions"})


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
    sold = data.trimmed_shares(symbol)
    if sold and (req.shares is None or req.shares <= sold + 1e-9):
        raise HTTPException(
            422,
            f"Share count must stay above the {sold:g} shares already trimmed. Undo a trim to reduce it further.",
        )
    data.save_position(symbol, req.entry_price, req.shares, _check_entry_date(req.entry_date))
    return _positions_payload()


@app.post("/api/positions/{symbol}/trims")
def trim_position(symbol: str, req: TrimRequest):
    """Sell part of a position. Selling every share still held is refused; that is Close position."""
    symbol = symbol.strip().upper()
    try:
        data.add_trim(symbol, req.shares, req.price)
    except data.PositionMissing:
        raise HTTPException(404, f"{symbol} is not in Positions")
    except data.TrimRejected as exc:
        raise HTTPException(422, str(exc))
    _publish_positions()
    return _positions_payload()


@app.delete("/api/positions/{symbol}/trims/{trim_id}")
def undo_trim(symbol: str, trim_id: int):
    """Delete one recorded trim and restore its shares to the position."""
    symbol = symbol.strip().upper()
    try:
        data.delete_trim(symbol, trim_id)
    except data.PositionMissing:
        raise HTTPException(404, f"Trim {trim_id} is not on {symbol}")
    _publish_positions()
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
    """$NASI, CNN Fear & Greed, and breadth of the symbols this scanner tracks.

    Advancers and 52-week highs/lows are counted from the scan rows and daily bars already
    in memory. They are not a Nasdaq or NYSE exchange statistic, and this route does not
    download prices.
    """
    payload = fetch_breadth()
    counts = universe_breadth(State.scan, State.daily)
    payload["issues"] = None if counts is None else counts["issues"]
    payload["highs_lows"] = None if counts is None else counts["highs_lows"]
    # Exchange-wide Nasdaq issues, fetched by the background job; only for the universe counts' session.
    session = max((str(r.get("as_of")) for r in State.scan if r.get("as_of")), default=None) if counts else None
    payload["nasdaq_issues"] = breadth_data.nasdaq_issues(session)
    return payload


@app.get("/api/market")
def market(tf: str = Query("W", pattern="^(M|W|D|3M|6M)$"), bars: int = Query(60, ge=10, le=300)):
    """State of the Market cards: QQQ, SPY and IWM, in that order."""
    _ensure_charts()
    by_symbol = {r["symbol"]: r for r in State.scan}
    active = quotes.active_quotes()
    out = etf_cards(MARKET_ETFS, by_symbol, State.daily, tf, bars, active)
    # The call and the market score use the same premarket / after-hours price the cards show.
    prices = {sym: q.price for sym, q in active.items()}
    return {"tf": tf, "as_of": State.scan_key, "etfs": out, "trend": index_trend(State.daily, prices)}


# Last, so every /api route above wins over the UI catch-all. No-op without a built web/dist.
mount_ui(app)
