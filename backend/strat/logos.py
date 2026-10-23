"""Company / fund logos by ticker, fetched once from a free source and kept on disk.

``/api/logo/{symbol}`` serves them so the browser never calls the third party directly: one fetch per symbol per
dyno (the disk cache), long browser cache headers, and the source can be swapped here without touching the UI.

Source: Parqet's free logo API (``assets.parqet.com/logos/symbol/{SYMBOL}``), no key. Free use requires attribution,
which the UI footer carries ("Logos by Parqet"). PNG is asked for first; a few symbols only exist as SVG, which is
served with a sandboxing CSP so it can never run script on our origin. Misses are remembered for a day.

Memory: nothing is held in RAM beyond the one response being written; files are ~0.5-5 KB each (~1 MB for the
whole universe).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx

from .config import DATA_DIR

log = logging.getLogger(__name__)

LOGO_DIR = Path(os.environ.get("STRAT_LOGO_DIR", DATA_DIR / "logos"))
SOURCE = "https://assets.parqet.com/logos/symbol/{symbol}"
SOURCE_NAME = "Parqet"
SOURCE_URL = "https://parqet.com"
MAX_BYTES = 256 * 1024
MISS_TTL_S = 24 * 3600
FETCH_TIMEOUT_S = 6.0
SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,9}$")

# Browser cache: a week for a logo, a day for a miss (so the letter avatar does not re-ask on every page).
HIT_CACHE = "public, max-age=604800, stale-while-revalidate=86400"
MISS_CACHE = "public, max-age=86400"
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"

_MAGIC = {
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"GIF8": ("gif", "image/gif"),
}
TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp", "svg": "image/svg+xml"}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass(frozen=True)
class Logo:
    path: Path
    media_type: str


def normalize(symbol: str) -> Optional[str]:
    """Upper-case ticker if it looks like one (letters, digits, '.' or '-', up to 10 chars), else None."""
    s = (symbol or "").strip().upper()
    return s if SYMBOL_RE.match(s) else None


def sniff(body: bytes) -> Optional[tuple[str, str]]:
    """(extension, media type) for a raster image or SVG, None for anything else (HTML error pages etc.)."""
    for magic, kind in _MAGIC.items():
        if body.startswith(magic):
            return kind
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp", "image/webp"
    head = body[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in body[:2048].lower()):
        return "svg", "image/svg+xml"
    return None


def _fetch_parqet(symbol: str, client: httpx.Client) -> Optional[bytes]:
    for url in (SOURCE.format(symbol=symbol) + "?format=png", SOURCE.format(symbol=symbol)):
        try:
            r = client.get(url)
        except httpx.HTTPError as e:
            log.info("logo fetch %s failed: %s", symbol, e)
            raise
        if r.status_code == 200 and 0 < len(r.content) <= MAX_BYTES and sniff(r.content):
            return r.content
    return None


def _cached(symbol: str, root: Path) -> Optional[Logo]:
    for ext, media in TYPES.items():
        p = root / f"{symbol}.{ext}"
        if p.exists():
            return Logo(p, media)
    return None


def _lock(symbol: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(symbol, threading.Lock())


def get_logo(
    symbol: str,
    *,
    root: Optional[Path] = None,
    fetch: Optional[Callable[[str], Optional[bytes]]] = None,
    now: Optional[float] = None,
) -> Optional[Logo]:
    """The cached logo file for ``symbol``, fetching it once if needed. None for a miss (remembered for a day)."""
    sym = normalize(symbol)
    if sym is None:
        return None
    root = root or LOGO_DIR
    now = time.time() if now is None else now
    hit = _cached(sym, root)
    if hit:
        return hit
    miss = root / f"{sym}.miss"
    if miss.exists() and now - miss.stat().st_mtime < MISS_TTL_S:
        return None
    with _lock(sym):
        hit = _cached(sym, root)
        if hit:
            return hit
        try:
            if fetch is not None:
                body = fetch(sym)
            else:
                with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=True, headers={"User-Agent": "TiltKiller/1.0"}) as c:
                    body = _fetch_parqet(sym, c)
        except Exception:
            return None  # network trouble: not remembered as a miss, the next request tries again
        root.mkdir(parents=True, exist_ok=True)
        kind = sniff(body) if body else None
        if kind is None:
            miss.touch()
            os.utime(miss, (now, now))
            return None
        ext, media = kind
        tmp = root / f".{sym}.{ext}.tmp"
        tmp.write_bytes(body)
        tmp.replace(root / f"{sym}.{ext}")
        miss.unlink(missing_ok=True)
        return Logo(root / f"{sym}.{ext}", media)
