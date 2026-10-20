"""Optional child-process fetch (STRAT_FETCH_SUBPROCESS=1), for small hosts such as a 512 MB Heroku dyno.

A full history download and the earnings lookup leave a few hundred MB of fragmented heap
behind. Those two run in a short-lived child so the memory returns to the OS when the child
exits. A 5-day poll and the index-quote fetch are smaller than a second Python interpreter
(pandas and yfinance are ~100 MB, and the dyno bills parent and child together), so they run
in the API process.
"""

from __future__ import annotations

import multiprocessing
import os
from typing import Callable, Optional

ProgressFn = Callable[[int, int, str], None]


def enabled() -> bool:
    return os.environ.get("STRAT_FETCH_SUBPROCESS", "").strip().lower() in ("1", "true", "yes")


def use_child(full: bool, with_earnings: bool) -> bool:
    """True when this refresh is large enough that a child process pays for itself.

    The child is the full history download (``full``) and any pass that also refreshes
    earnings. The 15-minute 5-day poll sets neither.
    """
    return enabled() and (full or with_earnings)


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


def extended_prices() -> dict[str, float]:
    """Latest index prints, in this process.

    The quote is a few symbols and one request. Spawning a child for it costs more
    memory than the download, and the dyno counts both processes.
    """
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
