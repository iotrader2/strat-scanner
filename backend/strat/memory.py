"""Process memory for the refresh path.

Heroku's R14 quota is resident memory plus swap, summed across every process on
the dyno. ``rss_mb`` reports that pair for this process. ``release_heap`` gives
freed glibc pages back to the OS; without it, a reload's temporary peak becomes
the new steady state.
"""

from __future__ import annotations

import gc
from pathlib import Path


def rss_kb() -> tuple[int, int]:
    """``(VmRSS, VmSwap)`` in kilobytes. ``(0, 0)`` when ``/proc`` is unavailable."""
    try:
        text = Path("/proc/self/status").read_text()
    except OSError:
        return (0, 0)
    rss = swap = 0
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            rss = int(line.split()[1])
        elif line.startswith("VmSwap:"):
            swap = int(line.split()[1])
    return rss, swap


def rss_mb() -> float:
    """Resident set plus swap, in megabytes. This is what a dyno quota counts."""
    rss, swap = rss_kb()
    return (rss + swap) / 1024


def format_rss() -> str:
    rss, swap = rss_kb()
    return f"rss={rss / 1024:.0f}MB swap={swap / 1024:.0f}MB"


def release_heap() -> None:
    """Collect unreachable frames, then ask glibc to return the free pages.

    Linux only. Other platforms still run ``gc.collect()``.
    """
    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        return
