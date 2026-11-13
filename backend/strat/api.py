"""Local HTTP API consumed by the web UI (bound to 127.0.0.1 only)."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
import time
from datetime import date, datetime, timedelta
from typing import Literal, Mapping, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .alpaca import AlpacaError
from . import alerts as alert_rules
from . import alerts_live, alerts_store, ariel_setups, chart15m, config, data, earnings, fetch_worker, logos, memory, quotes, trims, userdb, watch15m
from .hub import hub
from .stage import StageGateMiddleware, configure_logging, mount_ui, use_private_yfinance_cache
from .provider import live_bars_enabled
from .scheduler import (
    ET,
    archive_through,
    decide,
    fetch_period,
    now_et,
    previous_weekday,
    scheduler_sleep,
    session_phase,
    watchlist_reset_target,
)
from . import breadth as breadth_data
from .breadth import fetch_breadth, universe_breadth
from .trend import index_trend
from .members import backfill_industries, effective_universe, extra_members, refresh_earnings
from .leadership import BENCHMARK, LEADER_MIN_RS, LEADERS_MIN_SCORE, in_leaders_scan
from .perf import MomentumRanks, Perf
from .scanner import ScanResult, chart_payload, etf_cards, scan_all, scan_symbol, short_rs_for, theme_cards
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
    short_rs: dict = {}
    theme_map: Optional[ThemeMap] = None
    version: int = 0
    quoting: bool = False
    # The one background job allowed at a time ("refresh", "quotes", "earnings"), held from the start of its
    # download until its rescan has finished. Two jobs never download, write the cache or hold a second copy
    # of the universe in memory together.
    job: Optional[str] = None
    # The watchlist / positions gained a symbol: seed its 15-minute EMA history on the next free slot.
    lists_dirty: bool = True


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


_SLIM_SETUP_KEYS = ("tf", "kind", "label", "trigger", "triggered", "live", "stop", "side")


def _slim_row(r: dict) -> dict:
    """A list row: every setup kept (the per-setup Setups views need them) but without the long detail text."""
    out = {k: v for k, v in r.items() if k != "setups"}
    out["setups"] = [{k: s.get(k) for k in _SLIM_SETUP_KEYS} for s in r.get("setups") or []]
    return out


def _opening_ranges() -> dict[str, tuple[float, float]]:
    """Today's 15-minute opening ranges (high, low): the Episodic Pivot entry levels, from the live Alpaca bars."""
    if not live_bars_enabled():
        return {}
    try:
        from . import intraday as intraday_bars

        return intraday_bars.opening_ranges()
    except Exception:  # noqa: BLE001 — a missing opening range must never break the scan
        log.exception("opening range highs failed")
        return {}


def _scan_one(member: Member, daily) -> Optional[dict]:
    """Scan one symbol against the current theme ranking and momentum distributions."""
    qqq_daily = State.daily.get(BENCHMARK)
    bench_close = None if qqq_daily is None or qqq_daily.empty else qqq_daily["close"]
    srs, peers = short_rs_for(member, daily, qqq_daily, State.short_rs)
    return scan_symbol(
        member, daily, State.strengths, State.ranks, State.theme_map, State.qqq, prior=State.prior,
        benchmark_close=bench_close, srs=srs, srs_peers=peers,
        opening_high=_opening_ranges().get(member.symbol, (None, None))[0],
        opening_low=_opening_ranges().get(member.symbol, (None, None))[1],
    )


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
            # After the scan, so a reset that lands in this job (the poll ran past 16:01) screens
            # the session bar this poll just wrote, not the scan from the previous poll.
            _refresh_watch15m()
            memory.release_heap()
            _release_job()
            _log_rss("end", full=full, period=period or "", fetch=fetch)


def _refresh_nasdaq_issues() -> None:
    """Nasdaq advancers / decliners and new highs / lows (WSJ diary), inside the refresh's job slot, on the refresh cadence.

    One ~2 KB request. Skipped for a cut-off view and when the background scheduler is off (tests, CLI).
    """
    if config.AS_OF or not config.scheduler_enabled():
        return
    try:
        breadth_data.refresh_nasdaq_issues()
    except Exception:
        log.exception("nasdaq issues refresh failed")


def _list_symbols() -> list[str]:
    return list(dict.fromkeys(data.watchlist() + [p["symbol"] for p in data.positions()]))


def _prev_close(symbol: str, day: date) -> Optional[float]:
    """Last regular close before ``day`` from the daily cache (the base for premarket % change)."""
    frame = State.daily.get(symbol)
    if frame is None or frame.empty:
        frame = data.load_daily(symbol)
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    closes = frame.loc[frame.index < pd.Timestamp(day), "close"].dropna()
    return float(closes.iloc[-1]) if len(closes) else None


def _refresh_watch15m() -> None:
    """Premarket prints and 15-minute EMAs for the watchlist + positions (Alpaca), inside the job slot.

    Two or three small requests per poll for a handful of symbols. Skipped for a cut-off view, when
    the scheduler is off (tests, CLI) and when Alpaca is not the data source.
    """
    if config.AS_OF or not config.scheduler_enabled() or not live_bars_enabled():
        return
    State.lists_dirty = False
    try:
        symbols = _list_symbols()
        stats = watch15m.refresh(symbols, _prev_close)
        log.info("watch15m %s", stats)
        if symbols:
            hub.publish({"type": "lists"})
    except Exception:
        log.exception("watchlist 15m refresh failed")
    _refresh_alerts()


def daily_setups(row: Mapping, side: str) -> list[dict]:
    """The row's daily setups on ``side`` ("long" / "short"), as the scanner lists them."""
    return [
        s for s in row.get("setups") or []
        if s.get("tf") == "D" and (s.get("side") or "long") == side
    ]


def _alertable(row: Mapping) -> bool:
    """Stocks and ETFs (watchlist and off-universe names included); theme indexes cannot be traded."""
    return row.get("kind", "stock") in ("stock", "etf")


def theme_in_band(row: Mapping, side: str, settings: alert_rules.Settings) -> bool:
    """True when the theme gate is off, or the name's primary theme is in the top band (long) or bottom band (short).

    A name with no theme is out while the gate is on. ``theme_top_pct`` of 25 is the top or bottom quartile.
    """
    if not settings.theme_gate:
        return True
    strength = row.get("theme_strength") or {}
    rank, total = strength.get("rank"), strength.get("total")
    if not isinstance(rank, int) or not isinstance(total, int) or total <= 0:
        return False
    slots = max(1, math.ceil(total * float(settings.theme_top_pct) / 100.0))
    if side == "long":
        return rank <= slots
    return rank > total - slots


def short_setup_on(setup: Mapping, settings: alert_rules.Settings) -> bool:
    """Whether this short daily setup is one of the toggles that are on."""
    kind = str(setup.get("kind") or "")
    if kind == "ma-overcut-fail":
        label = str(setup.get("label") or "")
        if "10-day" in label:
            return bool(settings.short_ma10)
        if "20-day" in label:
            return bool(settings.short_ma20)
        if "50-day" in label:
            return bool(settings.short_ma50)
        return False
    key = {
        "delayed-hvc-short": "short_hvc",
        "ema-crossback-short": "short_crossback",
        "overcut-fail": "short_overcut",
        "wedge-drop": "short_wedge",
        "flat-base-breakdown": "short_flat",
        "low-tight-flag": "short_flag",
        "gap-down-pivot": "short_gap",
    }.get(kind)
    return bool(getattr(settings, key)) if key else False


def qualifying_setups(row: Mapping, side: str, settings: alert_rules.Settings) -> list[dict]:
    """Daily setups on ``side`` that the current rule settings will actually alert."""
    found = daily_setups(row, side)
    if side == "short":
        return [s for s in found if short_setup_on(s, settings)]
    if settings.long_pending_only:
        return [s for s in found if not s.get("triggered")]
    return found


def alert_symbols(rows: list[dict], settings: alert_rules.Settings) -> list[str]:
    """Long-side alert names: a stock or ETF with a qualifying long daily setup, highest score first.

    With the theme gate on, the name's primary theme has to sit in the top ``theme_top_pct`` of themes.
    Average dollar volume and ATR % are applied before the cap. At most ``max_symbols``.
    The 15-minute EMA only times the entry. Names the user added are not in this list.
    """
    picked = [
        r for r in rows
        if _alertable(r) and qualifying_setups(r, "long", settings) and theme_in_band(r, "long", settings)
        and alert_rules.passes_name_screen(r, settings)
    ]
    picked.sort(key=lambda r: (-(r["score"] if isinstance(r.get("score"), (int, float)) else -1e9), r["symbol"]))
    return [r["symbol"] for r in picked[: settings.max_symbols]]


def alert_short_symbols(rows: list[dict], settings: alert_rules.Settings) -> list[str]:
    """Short-side alert names: a stock or ETF with an allowed short daily setup, weakest RS first.

    With the theme gate on, the primary theme has to sit in the bottom ``theme_top_pct`` of themes.
    Average dollar volume and ATR % are applied before the cap. At most ``max_short_symbols``.
    Empty when shorts are switched off. Names the user added are not screened here.
    """
    if not settings.shorts:
        return []
    picked = [
        r for r in rows
        if _alertable(r) and qualifying_setups(r, "short", settings) and theme_in_band(r, "short", settings)
        and alert_rules.passes_name_screen(r, settings)
    ]
    picked.sort(key=lambda r: (r["rs"] if isinstance(r.get("rs"), (int, float)) else 1e9, r["symbol"]))
    return [r["symbol"] for r in picked[: settings.max_short_symbols]]


def _manual_alert_names(rows: list[dict]) -> list[str]:
    """Stocks and ETFs the user added or starred, oldest first, with ATR % above the hard floor.

    Auto-added names and themes are left out.
    """
    manual = {sym for sym, src in data.watch_sources().items() if src == data.WATCH_MANUAL}
    if not manual:
        return []
    by_scan = {r.get("symbol"): r for r in rows}
    extra_kind = {e["symbol"]: e.get("kind") for e in data.extra_symbols()}
    universe_kind: dict[str, str] | None = None

    def alertable(sym: str) -> bool:
        nonlocal universe_kind
        row = by_scan.get(sym)
        if row is not None:
            return _alertable(row)
        kind = extra_kind.get(sym)
        if kind is None:
            if universe_kind is None:
                universe_kind = {m.symbol: m.kind for m in load_universe()}
            kind = universe_kind.get(sym)
        return kind in ("stock", "etf")

    # Manual names skip the slider filters but not the hard ATR floor: no scan row or ATR % <= the floor, no alert.
    return [
        sym for sym in data.watchlist()
        if sym in manual and alertable(sym) and alert_rules.above_atr_floor(by_scan.get(sym))
    ]


def alert_refresh_inputs(rows: list[dict], settings: alert_rules.Settings) -> tuple[list[str], list[str], dict]:
    """Names to check this pass: (longs, shorts, daily-setup refs).

    Qualifying names are capped as usual. With ``alert_manual_watchlist`` on, a stock or ETF the user
    added is also checked on the long side even with no daily setup and outside the theme gate, and it
    does not count toward ``max_symbols``. One that already qualifies as a short stays a short.
    A manual name that was not already a normal long is tagged with the Watchlist setup ref.
    """
    longs = alert_symbols(rows, settings)
    shorts = alert_short_symbols(rows, settings)
    labels = alert_daily_labels(rows, settings)
    if not settings.alert_manual_watchlist:
        return longs, shorts, labels
    long_set, short_set = set(longs), set(shorts)
    for sym in _manual_alert_names(rows):
        if sym in short_set:
            continue
        if sym not in long_set:
            longs.append(sym)
            sides = dict(labels.get(sym) or {})
            have = list(sides.get("long") or [])
            if not any(isinstance(ref, dict) and ref.get("kind") == alert_rules.WATCHLIST_SETUP["kind"] for ref in have):
                have.append(dict(alert_rules.WATCHLIST_SETUP))
            sides["long"] = have
            sides.setdefault("short", [])
            labels[sym] = sides
    return longs, shorts, labels


def _alert_name_count() -> int:
    settings = alerts_store.load_settings()
    longs, shorts, _ = alert_refresh_inputs(State.scan, settings)
    return len(set(longs) | set(shorts))


def alert_daily_labels(rows: list[dict], settings: Optional[alert_rules.Settings] = None) -> dict[str, dict[str, list[dict]]]:
    """symbol -> {"long": [setup refs], "short": [setup refs]} for the setups the rules will alert.

    Each ref is ``{kind, label, side}`` plus ``period`` for a 10/20/50-day moving-average setup.
    The live poll stores that list on the alert so metrics can group by daily setup.
    """
    settings = settings or alert_rules.Settings()
    out: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        if not _alertable(r):
            continue
        sides = {
            side: [alert_rules.daily_setup_ref(s) for s in qualifying_setups(r, side, settings)]
            for side in ("long", "short")
        }
        if sides["long"] or sides["short"]:
            out[r["symbol"]] = sides
    return out


def _sync_alert_watchlist(settings: alert_rules.Settings, now=None) -> Optional[dict]:
    """Add the names that qualify for alerts, and clear the auto list once after the close.

    During the session this only appends. At and after 16:01 America/New_York the first call
    clears alert names, then adds the names that qualify for the next session, in that same
    call. The rows come from the current scan, which overlays today's session bar, so the
    list is built from the day that just ended. Weekends are left alone. A scan that has not
    finished yet does not clear anything.
    """
    if config.AS_OF or State.scan_key is None:
        return None
    longs = alert_symbols(State.scan, settings)
    shorts = alert_short_symbols(State.scan, settings)
    names = list(dict.fromkeys([*longs, *shorts]))
    labels = alert_daily_labels(State.scan, settings)
    long_set, short_set = set(longs), set(shorts)
    setups = {}
    for sym in names:
        sides = labels.get(sym) or {}
        refs = []
        if sym in long_set:
            refs.extend(sides.get("long") or [])
        if sym in short_set:
            refs.extend(sides.get("short") or [])
        setups[sym] = refs
    try:
        changed = data.sync_alert_watchlist(
            names, setups=setups, include_manual=bool(settings.reset_manual), now=now,
            snapshot_rows={r["symbol"]: r for r in State.scan},
        )
    except Exception:
        log.exception("alert watchlist sync failed")
        return None
    if changed["reset"] or changed["added"] or changed["setups_changed"]:
        State.lists_dirty = True
        hub.publish({"type": "lists"})
        log.info(
            "watchlist session=%s reset=%s added=%s setups=%s",
            changed["session"], changed["reset"], len(changed["added"]), changed["setups_changed"],
        )
    return changed


def _close_watchlist_reset(now) -> bool:
    """Run today's post-close watchlist reset. True once that next session is stored.

    Called from the scheduler at and after 16:01 ET, which is after the closing poll window,
    and again on a later start if that close was missed. The scan is rebuilt first so the
    overlay of today's session bar (the cash session that just ended) is what the next
    session's names are chosen from. A scan that is not ready yet returns False and the
    scheduler tries again. A mid-session call is not made: ``watchlist_reset_target`` is None
    before 16:01, so a restart then never reaches this.
    """
    target = watchlist_reset_target(now)
    if target is None or config.AS_OF:
        return False
    if data.watchlist_session() == target.isoformat():
        return True
    _ensure_scan(force=True)
    if State.scan_key is None:
        return False
    changed = _sync_alert_watchlist(alerts_store.load_settings(), now=now)
    return bool(changed) and changed.get("session") == target.isoformat()


def _prior_daily_bars(symbols: list[str], session: date) -> dict[str, list]:
    """Prior-session daily bars per symbol from ``State.daily`` (excludes ``session``'s bar)."""
    out: dict[str, list] = {}
    for sym in symbols:
        bars = alert_rules.prior_daily_bars_from_frame(State.daily.get(sym), session)
        if bars:
            out[sym] = bars
    return out


def _refresh_alerts() -> None:
    """15-minute EMA entries on the same poll. No-op outside the regular session.

    Qualifying names, plus names the user added to the watchlist when that setting is on. The manual
    names are part of the symbol list, so the EMA history fetch covers off-universe tickers too.
    """
    try:
        settings = alerts_store.load_settings()
        _sync_alert_watchlist(settings)
        longs, shorts, labels = alert_refresh_inputs(State.scan, settings)
        session = now_et().date()
        prior_bars = _prior_daily_bars(list(dict.fromkeys([*longs, *shorts])), session)
        stats = alerts_live.refresh(
            longs, settings=settings, short_symbols=shorts, daily_setups=labels,
            prior_daily_bars=prior_bars, scan_rows={r["symbol"]: r for r in State.scan if r.get("symbol")},
        )
        if stats.get("skipped"):
            if stats.get("prepared"):
                log.info("alerts prepared EMA history for %s symbols", stats["prepared"])
            return
        log.info(
            "alerts symbols=%s alerts=%s new=%s triggered=%s trimmed=%s stop_moved=%s carried=%s updated=%s removed=%s requests=%s",
            stats["symbols"], stats["alerts"], len(stats["inserted"]), len(stats.get("triggered", [])),
            len(stats.get("trimmed", [])), len(stats.get("stop_moved", [])), stats.get("carried", 0),
            stats["updated"], stats.get("removed", 0), stats["requests"],
        )
        if stats["inserted"] or stats["updated"] or stats.get("removed"):
            hub.publish({
                "type": "alerts",
                "new": [a["id"] for a in stats["inserted"] if not a["late"]],
                "triggered": [a["id"] for a in stats.get("triggered", [])],
                # One entry per new thirds-ladder sell: {id, symbol, setup, step, client_order_id}.
                "trimmed": stats.get("trimmed", []),
                # One entry per new intraday stop move: {id, symbol, setup, step, stop_price, client_order_id}.
                "stop_moved": stats.get("stop_moved", []),
            })
    except Exception:
        log.exception("alerts refresh failed")


def _run_watch15m() -> None:
    try:
        _refresh_watch15m()
    finally:
        _release_job()


def _run_close_check() -> None:
    try:
        _refresh_alerts()
    finally:
        _release_job()


def start_close_check() -> bool:
    """The 15:59 ET alerts pass: today's price for the daily trim ladder (see ``alerts_live``)."""
    if not _claim_job("alerts_close"):
        return False
    threading.Thread(target=_run_close_check, daemon=True).start()
    return True


def start_watch15m() -> bool:
    """Premarket poll for the two small lists (the universe stays on its own cadence)."""
    if not _claim_job("lists"):
        return False
    threading.Thread(target=_run_watch15m, daemon=True).start()
    return True


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
        _refresh_watch15m()
        _release_job()


def _refresh_earnings(max_age_hours: float, progress=None) -> None:
    refresh_earnings(_universe(), max_age_hours, progress)


def _earnings_window() -> int:
    """Calendar days, today included. One saved setting for every earnings warning."""
    return alerts_store.load_settings().earnings_window_days


def _with_earnings(rows: list[dict]) -> list[dict]:
    """Attach the upcoming-earnings warning to each stock row inside the user's window."""
    cached = data.load_earnings()
    today = date.fromisoformat(config.AS_OF) if config.AS_OF else earnings.today_et()
    window = _earnings_window()
    return [
        {**r, "earnings": earnings.upcoming(cached.get(r["symbol"]), today, window) if r.get("kind") == "stock" else None}
        for r in rows
    ]


def _kinds_for(symbols: list[str]) -> dict[str, Optional[str]]:
    """Kind for symbols that are not already on a scan row. Unknown names stay unset (no warning)."""
    need = set(symbols)
    found: dict[str, Optional[str]] = {r["symbol"]: r.get("kind") for r in State.scan if r.get("symbol") in need}
    missing = [s for s in need if s not in found]
    if not missing:
        return found
    base = load_universe()
    by = {m.symbol: m.kind for m in base + extra_members(only_tracked=False, base=base)}
    for symbol in missing:
        if symbol in by:
            found[symbol] = by[symbol]
    return found


def _earnings_for_symbols(symbols: list[str]) -> dict[str, Optional[dict]]:
    """Same warning as the scan rows, for symbols that do not carry their own kind (alert rows)."""
    kinds = _kinds_for(symbols)
    rows = _with_earnings([{"symbol": s, "kind": kinds.get(s)} for s in dict.fromkeys(symbols)])
    return {r["symbol"]: r["earnings"] for r in rows}


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
    result = scan_all(_universe(), State.daily, State.theme_map, opening_ranges=_opening_ranges())
    State.result, State.scan = result, result.rows
    State.strengths, State.ranks, State.qqq, State.prior = result.strengths, result.ranks, result.qqq, result.prior
    State.short_rs = result.short_rs
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


# A standing archive error used to be logged and retried on every scheduler tick (about 20s).
_ARCHIVE_RETRY_MIN = 60.0
_ARCHIVE_RETRY_MAX = 600.0
_archive_failures = 0
_archive_retry_not_before = 0.0
_archive_failure_key = ""


def _reset_archive_retry() -> None:
    global _archive_failures, _archive_retry_not_before, _archive_failure_key
    _archive_failures = 0
    _archive_retry_not_before = 0.0
    _archive_failure_key = ""


def _remember_archive_failure(exc: BaseException) -> None:
    """Log a new failure once, then wait progressively longer before trying again."""
    global _archive_failures, _archive_retry_not_before, _archive_failure_key
    _archive_failures += 1
    delay = min(_ARCHIVE_RETRY_MAX, _ARCHIVE_RETRY_MIN * (2 ** (_archive_failures - 1)))
    _archive_retry_not_before = time.monotonic() + delay
    key = f"{type(exc).__name__}: {exc}"
    if key != _archive_failure_key:
        _archive_failure_key = key
        log.exception("alert archive failed; next try in %ds", int(delay))


def _catch_up_alert_archive(done: date | None, now) -> date | None:
    """Move closed sessions into alerts history. Once per cutoff, including while a download holds the job slot.

    A dyno that wakes after 16:05 should not wait on the history fetch. The move is one short transaction.
    A failure leaves ``done`` unchanged. The same error is logged once, and the next try waits, doubling
    from one minute up to ten, instead of repeating on every 20s tick. The auto-archive setting off also
    leaves ``done`` unchanged, so turning the setting on later still archives.
    """
    through = archive_through(now)
    if done is not None and through <= done:
        return done
    if time.monotonic() < _archive_retry_not_before:
        return done
    try:
        result = alerts_store.archive_if_due(now)
    except Exception as exc:
        _remember_archive_failure(exc)
        return done
    if _archive_failures:
        log.info("alert archive recovered after %s failed attempt(s)", _archive_failures)
        _reset_archive_retry()
    if result["skipped"]:
        return done
    # Archive marks the end of the session: clear in-memory skip counts for the next day.
    alert_rules.reset_skip_counts()
    dropped = result.get("dropped") or 0
    if result["moved"] or dropped:
        suffix = f" and removed {dropped} live duplicates" if dropped else ""
        log.info("archived %s alerts through %s%s", result["moved"], result["through"], suffix)
        hub.publish({"type": "alerts", "new": []})
    return through


def _boot() -> None:
    if config.AS_OF:
        with _scan_lock:
            _ensure_scan(force=True)
        return
    _catch_up_alert_archive(None, now_et())
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
    last_lists = None
    archived_through: date | None = None
    # Eastern date whose 16:01 watchlist reset has been stored. In memory only: a restart
    # after 16:01 checks the stored session and runs the reset if that close was missed.
    close_reset_on: date | None = None
    # Eastern date whose 15:59 daily trim pass has started.
    close_check_on: date | None = None
    while True:
        time.sleep(scheduler_sleep(now_et(), live_bars_enabled()))
        now = now_et()
        archived_through = _catch_up_alert_archive(archived_through, now)
        if config.AS_OF or State.refreshing or State.quoting or State.job is not None:
            continue
        if watchlist_reset_target(now) is not None and close_reset_on != now.date():
            try:
                if _close_watchlist_reset(now):
                    close_reset_on = now.date()
            except Exception:
                log.exception("post-close watchlist reset failed")
        if session_phase(now) not in ("premarket", "after_hours") and data.clear_index_quotes():
            _publish_index_quotes()
        live = live_bars_enabled()
        if live and close_check_on != now.date() and alerts_live.close_check_due(now):
            if start_close_check():
                close_check_on = now.date()
            continue
        kind = decide(now, data.newest_bar_date(), last_poll, last_extended, aligned=live, last_lists=last_lists)
        if kind is None and live and State.lists_dirty:
            kind = "lists"
        if kind is None:
            continue
        if kind == "lists":
            if session_phase(now) == "premarket":
                last_lists = now
            start_watch15m()
        elif kind == "extended":
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
        "storage": userdb.describe(),
        "alert_skips_today": alert_rules.skip_counts(),
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
        # The daily setups as data/setups.yaml documents them (the Setups dropdown's hover text).
        "setups": ariel_setups.describe(),
        "setups_overview": ariel_setups.overview(),
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
    default P90), or an RS line versus QQQ that made a 52-week high in the last 5 sessions, with the trend intact,
    and a leadership score (``leadership_score``, not the setup score) strictly above ``LEADERS_MIN_SCORE`` (70). Raising ``min_rs`` above P90 tightens the percentile cut.
    A daily setup is not required; names without one are labelled in the row."""
    min_price = config.MIN_PRICE if min_price is None else min_price
    min_dollar_volume = config.MIN_DOLLAR_VOLUME if min_dollar_volume is None else min_dollar_volume
    cut = LEADER_MIN_RS if min_rs is None else min_rs
    rows = _with_earnings([
        _slim_row(r)
        for r in _ensure_scan()
        if r["price"] >= min_price
        and r["avg_dollar_volume"] >= min_dollar_volume
        and (include_etfs or r["kind"] == "stock")
        and (not leaders_only or in_leaders_scan(
            r["rs"], r["leadership"]["breakdown"], r.get("leadership_score", r["score"]), cut,
            rs_line_high=bool(r.get("rs_line_high")),
        ))
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


def _daily_ready(symbol: str) -> bool:
    frame = State.daily.get(symbol)
    return frame is not None and not frame.empty


@app.get("/api/symbol/{symbol}/bars15m")
def symbol_bars15m(symbol: str):
    """15-minute regular-session candles and 6/20/50/120 EMAs for one symbol.

    Fetched on demand and cached for that ticker only. A cold process loads the daily
    cache first (the same scan the chart page already needs); a warm process does not
    scan, and an unknown ticker never reaches Alpaca.
    """
    symbol = symbol.upper()
    if not _daily_ready(symbol) and not State.daily:
        _ensure_charts()
    if not _daily_ready(symbol):
        raise HTTPException(404, f"{symbol} is not in the cache")
    if not live_bars_enabled():
        raise HTTPException(503, "15-minute bars need the Alpaca feed")
    try:
        return chart15m.chart(symbol)
    except AlpacaError:
        log.warning("15-minute bars failed for %s", symbol, exc_info=True)
        raise HTTPException(502, "15-minute bars are unavailable") from None


class WatchRequest(BaseModel):
    symbol: str


class PositionRequest(BaseModel):
    symbol: str
    entry_price: Optional[float] = Field(None, gt=0)
    shares: Optional[float] = Field(None, gt=0)
    entry_date: Optional[date] = None
    side: Literal["long", "short"] = "long"


class PositionUpdate(BaseModel):
    entry_price: float = Field(gt=0)
    shares: Optional[float] = Field(None, gt=0)
    entry_date: date
    side: Optional[Literal["long", "short"]] = None  # None keeps the position's side


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
    stored = data.watch_setups()
    rows = _with_earnings([by_symbol[s] for s in symbols if s in by_symbol])
    for row in rows:
        row["watch_setups"] = stored.get(row["symbol"]) or []
    times = data.watchlist_times()
    return {
        "symbols": symbols,
        "rows": rows,
        "missing": [s for s in symbols if s not in by_symbol],
        "intraday": watch15m.snapshot(symbols),
        "loaded_at": times["loaded_at"],
        "updated_at": times["updated_at"],
    }


@app.get("/api/watchlist")
def get_watchlist():
    """Watched names with their full scan row, whether or not they still have a daily setup."""
    return _watchlist_payload()


@app.get("/api/watchlist/history")
def get_watchlist_history(day: Optional[str] = Query(None, alias="date")):
    """The watchlist as it stood at one day's close (read only). No date picks the latest stored day.

    Days are stored going forward by the post-close reset; there is nothing before the first one.
    Rows are the scan rows saved at that close, not today's prices.
    """
    dates = data.watchlist_history_dates()
    if day:
        try:
            chosen: Optional[str] = date.fromisoformat(day).isoformat()
        except ValueError:
            raise HTTPException(422, "date must be YYYY-MM-DD") from None
    else:
        chosen = dates[0] if dates else None
    stored = data.watchlist_history(chosen) if chosen else []
    rows = []
    for item in stored:
        if item["row"] is None:
            continue
        rows.append({**item["row"], "watch_setups": item["setups"], "watch_source": item["source"], "earnings": None})
    return {
        "date": chosen,
        "dates": dates,
        "symbols": [item["symbol"] for item in stored],
        "rows": rows,
        "missing": [item["symbol"] for item in stored if item["row"] is None],
        "snapshot_at": stored[0]["snapshot_at"] if stored else None,
    }


@app.post("/api/watchlist")
def add_watch(req: WatchRequest):
    """Add any ticker. Symbols outside the universe are validated and downloaded via yfinance first."""
    symbol, in_universe = _resolve_symbol(req.symbol)
    if symbol in data.watchlist():
        # A star on a name the alerts added keeps it when the post-close reset clears alert names.
        data.add_to_watchlist(symbol)
        return _watchlist_payload()
    if not in_universe and symbol not in data.tracked_symbols():
        _fetch_off_universe(symbol)
    data.add_to_watchlist(symbol)
    State.lists_dirty = True
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
        "intraday": watch15m.snapshot([p["symbol"] for p in held]),
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
    data.save_position(symbol, entry_price, req.shares, entry_date, side=req.side)
    data.remove_from_watchlist(symbol)
    State.lists_dirty = True
    _start_tracking(symbol, in_universe)
    return _positions_payload()


@app.put("/api/positions/{symbol}")
def update_position(symbol: str, req: PositionUpdate):
    symbol = symbol.strip().upper()
    current = next((p for p in data.positions() if p["symbol"] == symbol), None)
    if current is None:
        raise HTTPException(404, f"{symbol} is not in Positions")
    side = req.side or current.get("side") or "long"
    sold = data.trimmed_shares(symbol)
    if sold and side != (current.get("side") or "long"):
        raise HTTPException(422, "Undo the trims before switching a position between long and short.")
    if sold and (req.shares is None or req.shares <= sold + 1e-9):
        raise HTTPException(
            422,
            f"Share count must stay above the {sold:g} shares already trimmed. Undo a trim to reduce it further.",
        )
    data.save_position(symbol, req.entry_price, req.shares, _check_entry_date(req.entry_date), side=side)
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
    payload["nasdaq_highs_lows"] = breadth_data.nasdaq_highs_lows(session)
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
# ------------------------------------------------------------------------------------------------ alerts


class AckRequest(BaseModel):
    ids: Optional[list[int]] = None  # None: every unread alert


def _alerts_session(session: Optional[str]) -> str:
    if session and session != "today":
        try:
            return date.fromisoformat(session).isoformat()
        except ValueError:
            raise HTTPException(422, "session must be YYYY-MM-DD") from None
    return now_et().date().isoformat()


def _alert_ema5m(symbols: list[str]) -> dict[str, dict | None]:
    """Current 15-minute 6/20 EMA for these symbols, already computed by the lists poll.

    ``watch15m.snapshot`` only reads memory. It does not call Alpaca. A name that is on neither
    the watchlist nor in positions has no reading.
    """
    if not symbols:
        return {}
    snap = watch15m.snapshot(symbols)
    return {sym: snap[sym]["ema5m"] for sym in symbols}


def _decorate_alerts(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Scanner score and the earnings warning, the same fields the live alerts route adds."""
    rows = _attach_scores(rows)
    symbols = list(dict.fromkeys(row["symbol"] for row in rows))
    flags = _earnings_for_symbols(symbols)
    return [{**row, "earnings": flags.get(row["symbol"])} for row in rows], symbols


def industry_ranks(rows: list[dict]) -> dict[str, tuple[int, int]]:
    """Industry -> (rank, total): stock industries ranked by the median RS percentile of their members (1 = strongest).

    Industries are the Yahoo industries the scanner shows; ties go by name. Members without RS are left out.
    """
    groups: dict[str, list[float]] = {}
    for r in rows:
        ind, rs = r.get("industry"), r.get("rs")
        if r.get("kind", "stock") == "stock" and ind and isinstance(rs, (int, float)):
            groups.setdefault(str(ind), []).append(float(rs))
    medians = {}
    for ind, values in groups.items():
        values.sort()
        n = len(values)
        medians[ind] = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
    ranked = sorted(medians, key=lambda ind: (-medians[ind], ind))
    return {ind: (i, len(ranked)) for i, ind in enumerate(ranked, start=1)}


def _has_daily_setup(row: Mapping) -> bool:
    details = row.get("details")
    return isinstance(details, dict) and bool(details.get("daily_setups"))


def _alert_score(row: Mapping, scan: Optional[Mapping]) -> dict:
    """The setup score the trade was taken with (frozen on the alert when it fired), else the current scan score."""
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    frozen = details.get("score") if isinstance(details.get("score"), dict) else None
    now = None if scan is None else scan.get("score")
    if frozen:
        return {
            "score": frozen.get("score"),
            "score_raw": frozen.get("raw"),
            "score_max_raw": frozen.get("max_raw"),
            "score_breakdown": frozen.get("breakdown") or [],
            "score_at_entry": True,
            "scan_score_now": now,
        }
    return {
        "score": now,
        "score_raw": None if scan is None else scan.get("score_raw"),
        "score_max_raw": None if scan is None else scan.get("score_max_raw"),
        "score_breakdown": [] if scan is None else (scan.get("score_breakdown") or []),
        "score_at_entry": False,
        "scan_score_now": now,
    }


def _attach_scores(rows: list[dict]) -> list[dict]:
    """The scanner score, RS and industry (with its rank) for each alert's symbol, as the Stock Scanner shows them."""
    by_symbol = {r["symbol"]: r for r in State.scan if r.get("symbol")}
    ranks = industry_ranks(State.scan) if rows else {}
    attached = []
    for row in rows:
        scan = by_symbol.get(row["symbol"])
        industry = None if scan is None else scan.get("industry")
        rank = ranks.get(str(industry)) if industry else None
        price = None if scan is None else scan.get("price")
        r_now = alert_rules.open_r(row, price if isinstance(price, (int, float)) else None)
        attached.append({
            **row,
            "side": alert_rules.setup_side(str(row.get("setup"))),
            # Last price on the scan (refreshed every poll) and the open trade's R at that price.
            "price": price,
            "open_r": None if r_now is None else round(r_now, 3),
            "rs": None if scan is None else scan.get("rs"),
            "industry": industry,
            "industry_rank": rank[0] if rank else None,
            "industry_total": rank[1] if rank else None,
            **_alert_score(row, scan),
        })
    return attached


@app.get("/api/alerts")
def get_alerts(session: Optional[str] = None, symbol: Optional[str] = None):
    """One session's alerts (default today, Eastern date), newest first, plus the sessions that have any."""
    day = _alerts_session(session)
    # Only alerts that came from a daily setup (rows from the older score / laggard rules are left off).
    found = [r for r in alerts_store.list_alerts(session=day, symbol=symbol) if _has_daily_setup(r)]
    if day == now_et().date().isoformat():
        # Crossback positions held overnight from earlier sessions, until the daily trims or the stop close them.
        found += [
            {**r, "carried": True} for r in alerts_store.list_carried(day)
            if _has_daily_setup(r) and (symbol is None or r["symbol"] == symbol.upper())
        ]
    rows, symbols = _decorate_alerts(found)
    return {
        "session": day,
        "alerts": rows,
        "sessions": alerts_store.sessions(),
        "unread": alerts_store.unread_count(),
        "last_run": alerts_live.last_run(),
        "watchlist": data.watchlist(),
        # Names the next poll checks: every name with a long (or, shorts on, a short) daily setup.
        "universe": _alert_name_count(),
        "setups": alert_rules.SETUP_NAMES,
        # One small reading per symbol, not a copy on every alert row.
        "ema5m": _alert_ema5m(symbols),
    }


def _et_day(iso: Optional[str]) -> Optional[str]:
    if not iso:
        return None
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ET).date().isoformat()


def alert_orders(rows: list[dict], day: Optional[str] = None) -> list[dict]:
    """Buys, stop moves and thirds-ladder sells for the local order app, oldest first.

    One buy per alert of session ``day`` (``client_order_id`` = alert id; ``filled`` says whether the
    trigger traded), one ``stop`` per intraday stop move (``client_order_id`` = ``<id>-s<step>``: replace
    the working stop with ``stop_price``) and one sell per trim (``client_order_id`` = ``<id>-t<step>``).
    Trims and stop moves are listed on the Eastern day they happened, so a position held overnight
    shows its later trims on that later day. Stop and session-end exits are not listed: the app's own
    stop order covers those. ``day=None`` lists everything given.
    """
    out: list[dict] = []
    for r in rows:
        details = r.get("details") or {}
        base = {
            "alert_id": r["id"],
            "symbol": r["symbol"],
            "setup": r["setup"],
            "session": r["session"],
            "underlying": details.get("underlying"),
        }
        if day is None or r["session"] == day:
            out.append({
                **base,
                "kind": "buy",
                "client_order_id": str(r["id"]),
                "side": "buy",
                "status": r["status"],
                "filled": r["filled"],
                "price": r["fill_price"] if r["filled"] else r["trigger_price"],
                "stop_price": r["stop_price"],
                "at": r["fill_at"] or r["fired_at"],
            })
        for m in r.get("stops") or []:
            if day is None or _et_day(m.get("at")) == day:
                out.append({**base, "kind": "stop", **m})
        for t in r.get("trims") or []:
            if day is None or _et_day(t.get("at")) == day:
                out.append({**base, "kind": "trim", **t})
    order = {"buy": 0, "stop": 1, "trim": 2}
    out.sort(key=lambda o: (o["at"] or "", o["alert_id"], order[o["kind"]], o.get("step") or 0))
    return out


# Positions are held at most this long for the orders feed's look-back into earlier sessions.
ORDERS_LOOKBACK_DAYS = 120


@app.get("/api/alerts/orders")
def get_alert_orders(session: Optional[str] = None):
    """Order feed for the local order app: one Eastern day's buys, stop moves and trims (default today), oldest first."""
    day = _alerts_session(session)
    since = (date.fromisoformat(day) - timedelta(days=ORDERS_LOOKBACK_DAYS)).isoformat()
    live = alerts_store.list_alerts(start=since, end=day, limit=None)
    seen = {r["id"] for r in live}
    archived = [r for r in alerts_store.list_history(start=since, end=day, limit=None) if r["id"] not in seen]
    rows = [r for r in live + archived if _has_daily_setup(r)]
    return {"session": day, "orders": alert_orders(rows, day)}


@app.post("/api/alerts/history/clear")
def clear_alert_history():
    """Delete every live and archived alert. The stage gate covers this route the same way as the rest of the API."""
    cleared = alerts_store.clear_history()
    hub.publish({"type": "alerts", "new": []})
    return {"cleared": cleared}


@app.get("/api/alerts/history")
def get_alert_history(day: Optional[str] = Query(None, alias="date")):
    """One archived session, newest fire first. No date picks the latest archived day, or the previous weekday."""
    dates = alerts_store.history_dates()
    if day:
        try:
            chosen = date.fromisoformat(day).isoformat()
        except ValueError:
            raise HTTPException(422, "date must be YYYY-MM-DD") from None
    else:
        chosen = dates[0] if dates else previous_weekday(now_et()).isoformat()
    rows, symbols = _decorate_alerts(alerts_store.list_history(chosen))
    return {
        "date": chosen,
        "alerts": rows,
        "dates": dates,
        "setups": alert_rules.SETUP_NAMES,
        "ema5m": _alert_ema5m(symbols),
    }


@app.post("/api/alerts/ack")
def ack_alerts(req: AckRequest):
    n = alerts_store.acknowledge(req.ids)
    hub.publish({"type": "alerts", "new": []})
    return {"acknowledged": n, "unread": alerts_store.unread_count()}


@app.get("/api/alerts/metrics")
def alert_metrics(start: Optional[str] = None, end: Optional[str] = None, symbol: Optional[str] = None):
    """Per setup type: count, fill rate, win rate, average R, total R (closed filled trades), over a date range."""
    for v in (start, end):
        if v:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise HTTPException(422, "start / end must be YYYY-MM-DD") from None
    rows = alerts_store.list_for_metrics(start=start, end=end, symbol=symbol or None)
    return {
        "start": start,
        "end": end,
        "symbol": (symbol or "").upper() or None,
        "rows": alert_rules.metrics(rows),
        "symbols": alerts_store.metric_symbols(),
    }


@app.get("/api/alerts/score-report")
def alert_score_report(start: Optional[str] = None, end: Optional[str] = None):
    """Setup score vs R over closed trades: Spearman per component, R >= 1.5 hit rate per score quintile."""
    from . import score_report

    for v in (start, end):
        if v:
            try:
                date.fromisoformat(v)
            except ValueError:
                raise HTTPException(422, "start / end must be YYYY-MM-DD") from None
    return {"start": start, "end": end, **score_report.report(alerts_store.list_for_metrics(start=start, end=end))}


@app.get("/api/alerts/settings")
def get_alert_settings():
    return {"settings": alerts_store.load_settings().to_dict(), "defaults": alert_rules.Settings().to_dict(),
            "limits": {k: list(v) for k, v in alert_rules.SETTING_LIMITS.items()}}


@app.put("/api/alerts/settings")
def put_alert_settings(changes: dict):
    try:
        alerts_store.save_settings(changes)
    except alerts_store.SettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    return get_alert_settings()


@app.delete("/api/alerts/settings")
def reset_alert_settings():
    alerts_store.reset_settings()
    return get_alert_settings()


mount_ui(app)

