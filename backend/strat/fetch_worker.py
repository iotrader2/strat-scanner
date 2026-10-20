"""Optional child-process fetch (STRAT_FETCH_SUBPROCESS=1), for small hosts such as a 512 MB Heroku dyno.

Yahoo downloads and the 8-thread earnings lookup leave a few hundred MB of fragmented heap
behind in a long-lived process. Running each refresh in a short-lived spawned child hands that
memory back to the OS when the child exits; the API process only keeps the scan itself.
"""

from __future__ import annotations

import multiprocessing
import os
from typing import Callable, Optional

ProgressFn = Callable[[int, int, str], None]


def enabled() -> bool:
    return os.environ.get("STRAT_FETCH_SUBPROCESS", "").strip().lower() in ("1", "true", "yes")


def fetch(full: bool, period: Optional[str], with_earnings: bool, progress: ProgressFn) -> None:
    """Prices for the universe, then (optionally) industries and earnings dates, into the cache."""
    from . import data
    from .members import backfill_industries, effective_universe, refresh_earnings
    from .universe import load_universe

    members = effective_universe(load_universe())
    data.refresh([m.symbol for m in members], full=full, progress=progress, period=period)
    if with_earnings:
        members = effective_universe(load_universe())
        backfill_industries(members)
        refresh_earnings(members, 0, progress)


def _child(full: bool, period: Optional[str], with_earnings: bool, queue) -> None:
    from .stage import configure_logging, use_private_yfinance_cache

    configure_logging()
    use_private_yfinance_cache()
    try:
        fetch(full, period, with_earnings, lambda d, t, m: queue.put(("progress", d, t, m)))
        queue.put(("done",))
    except BaseException as exc:  # report, then let the parent raise
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _quote_child(queue) -> None:
    from .stage import configure_logging, use_private_yfinance_cache

    configure_logging()
    use_private_yfinance_cache()
    try:
        from .quotes import fetch_extended_prices

        queue.put(("prices", fetch_extended_prices()))
    except BaseException as exc:  # report, then let the parent raise
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def extended_prices_in_child() -> dict[str, float]:
    """Index pre/post prices in a short-lived process, so the Yahoo heap does not stay in the API."""
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_quote_child, args=(queue,), daemon=True)
    proc.start()
    prices: dict[str, float] = {}
    error = None
    try:
        while True:
            try:
                msg = queue.get(timeout=5)
            except Exception:  # queue.Empty: check the child is still alive
                if not proc.is_alive():
                    error = error or f"quote process exited with code {proc.exitcode}"
                    break
                continue
            if msg[0] == "prices":
                prices = msg[1] or {}
                break
            if msg[0] == "error":
                error = msg[1]
                break
    finally:
        proc.join(timeout=30)
        if proc.is_alive():
            proc.kill()
    if error:
        raise RuntimeError(error)
    return prices


def extended_prices() -> dict[str, float]:
    """Latest index prints. Uses the fetch child when STRAT_FETCH_SUBPROCESS is set."""
    if enabled():
        return extended_prices_in_child()
    from .quotes import fetch_extended_prices

    return fetch_extended_prices()


def fetch_in_child(full: bool, period: Optional[str], with_earnings: bool, progress: ProgressFn) -> None:
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_child, args=(full, period, with_earnings, queue), daemon=True)
    proc.start()
    error = None
    try:
        while True:
            try:
                msg = queue.get(timeout=5)
            except Exception:  # queue.Empty: check the child is still alive
                if not proc.is_alive():
                    error = error or f"fetch process exited with code {proc.exitcode}"
                    break
                continue
            if msg[0] == "progress":
                progress(*msg[1:])
            elif msg[0] == "error":
                error = msg[1]
                break
            else:
                break
    finally:
        proc.join(timeout=30)
        if proc.is_alive():
            proc.kill()
    if error:
        raise RuntimeError(error)
