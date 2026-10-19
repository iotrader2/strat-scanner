"""Staging-only helpers: an access gate and serving the built UI from the API process.

All inert for local dev. The gate has two modes:

- STAGE_TOKEN set (preferred): a secret link, /k/<token> or /?k=<token>, sets a long-lived
  HttpOnly cookie and redirects to /. Every other request (UI, API, WebSocket) needs that
  cookie; without it the answer is a plain 404, so the site looks like it is not there.
- STAGE_USER and STAGE_PASS set (and no STAGE_TOKEN): HTTP basic auth.

The built UI is served only when web/dist exists (or STRAT_STATIC_DIR points at it).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Optional

from starlette.responses import FileResponse, PlainTextResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

from .config import BACKEND_DIR

STATIC_DIR = Path(os.environ.get("STRAT_STATIC_DIR", BACKEND_DIR.parent / "web" / "dist"))


def stage_credentials() -> Optional[tuple[str, str]]:
    user = os.environ.get("STAGE_USER", "")
    password = os.environ.get("STAGE_PASS", "")
    return (user, password) if user and password else None


def _authorized(headers: list[tuple[bytes, bytes]], creds: tuple[str, str]) -> bool:
    for name, value in headers:
        if name.lower() != b"authorization":
            continue
        scheme, _, token = value.decode("latin-1").partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            user, _, password = base64.b64decode(token.strip()).decode("utf-8").partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return False
        ok_user = secrets.compare_digest(user.encode(), creds[0].encode())
        ok_pass = secrets.compare_digest(password.encode(), creds[1].encode())
        return ok_user and ok_pass
    return False


COOKIE_NAME = "stage_key"
COOKIE_MAX_AGE = 400 * 24 * 3600  # browsers cap cookie lifetime at 400 days
LINK_PREFIX = "/k/"


def stage_token() -> Optional[str]:
    return os.environ.get("STAGE_TOKEN") or None


def cookie_value(token: str) -> str:
    """What the cookie holds: an HMAC of the token, so the cookie itself never contains the link."""
    return hmac.new(token.encode(), b"tiltkiller-stage-cookie-v1", hashlib.sha256).hexdigest()


def _cookie_ok(headers: list[tuple[bytes, bytes]], token: str) -> bool:
    expected = cookie_value(token).encode()
    ok = False
    for name, value in headers:
        if name.lower() != b"cookie":
            continue
        for part in value.split(b";"):
            key, _, val = part.strip().partition(b"=")
            if key == COOKIE_NAME.encode():
                ok |= hmac.compare_digest(val.strip(), expected)
    return ok


def _link_token(scope) -> Optional[str]:
    """Token offered by a secret link: /k/<token> or /?k=<token>."""
    path = scope.get("path", "")
    if path.startswith(LINK_PREFIX):
        return path[len(LINK_PREFIX):].rstrip("/")
    if path == "/":
        from urllib.parse import parse_qs

        values = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("k")
        if values:
            return values[0]
    return None


async def _not_found(scope, receive, send) -> None:
    if scope["type"] == "websocket":
        # Closing before accept makes the server refuse the upgrade (HTTP 403).
        await send({"type": "websocket.close", "code": 1008})
        return
    await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)


class StageGateMiddleware:
    """Pure ASGI so it guards plain HTTP and the WebSocket upgrade alike."""

    def __init__(self, app, credentials: Optional[tuple[str, str]] = None, token: Optional[str] = None) -> None:
        self.app = app
        self.credentials = credentials
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        token = self.token or stage_token()
        if token:
            return await self._token_gate(token, scope, receive, send)
        creds = self.credentials or stage_credentials()
        if creds is None or _authorized(scope.get("headers", []), creds):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = PlainTextResponse(
            "Authentication required", status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="TiltKiller stage", charset="UTF-8"'},
        )
        await response(scope, receive, send)

    async def _token_gate(self, token: str, scope, receive, send) -> None:
        offered = _link_token(scope) if scope["type"] == "http" else None
        if offered is not None:
            if not hmac.compare_digest(offered.encode(), token.encode()):
                return await _not_found(scope, receive, send)
            response = RedirectResponse("/", status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
            response.set_cookie(
                COOKIE_NAME, cookie_value(token), max_age=COOKIE_MAX_AGE, path="/",
                httponly=True, secure=True, samesite="lax",
            )
            return await response(scope, receive, send)
        if _cookie_ok(scope.get("headers", []), token):
            return await self.app(scope, receive, send)
        return await _not_found(scope, receive, send)


# Older name, kept so existing imports keep working.
BasicAuthMiddleware = StageGateMiddleware


def mount_ui(app, static_dir: Path = STATIC_DIR) -> bool:
    """Serve the Vite build: hashed assets under /assets, real files by path, index.html for SPA routes."""
    index = static_dir / "index.html"
    if not index.is_file():
        return False
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    root = static_dir.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "ws")):
            return PlainTextResponse("Not Found", status_code=404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True


def configure_logging() -> None:
    """Send the app's own logs (fetcher progress, errors) to stdout when STRAT_LOG_LEVEL is set."""
    import logging

    level = os.environ.get("STRAT_LOG_LEVEL")
    if level:
        logging.basicConfig(level=level.upper(), format="%(levelname)s %(name)s: %(message)s")


def use_private_yfinance_cache() -> None:
    """Give this process its own writable yfinance tz/cookie cache when STRAT_YF_CACHE_DIR is set.

    yfinance keeps a small SQLite cache in ~/.cache/py-yfinance; the API process and a fetch child
    sharing it is what logged "database is locked" on Heroku.
    """
    base = os.environ.get("STRAT_YF_CACHE_DIR")
    if not base:
        return
    path = Path(base) / f"pid-{os.getpid()}"
    path.mkdir(parents=True, exist_ok=True)
    import yfinance as yf

    yf.set_tz_cache_location(str(path))
