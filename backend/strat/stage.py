"""Staging-only helpers: HTTP basic auth and serving the built UI from the API process.

Both are inert for local dev. Basic auth turns on only when STAGE_USER and STAGE_PASS are
set, and the built UI is served only when web/dist exists (or STRAT_STATIC_DIR points at it).
"""

from __future__ import annotations

import base64
import binascii
import os
import secrets
from pathlib import Path
from typing import Optional

from starlette.responses import FileResponse, PlainTextResponse
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


class BasicAuthMiddleware:
    """Pure ASGI so it guards plain HTTP and the WebSocket upgrade alike."""

    def __init__(self, app, credentials: Optional[tuple[str, str]] = None) -> None:
        self.app = app
        self.credentials = credentials

    async def __call__(self, scope, receive, send):
        creds = self.credentials or stage_credentials()
        if creds is None or scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if _authorized(scope.get("headers", []), creds):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            # Closing before accept makes the server answer the upgrade with 403.
            await send({"type": "websocket.close", "code": 1008})
            return
        response = PlainTextResponse(
            "Authentication required", status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="TiltKiller stage", charset="UTF-8"'},
        )
        await response(scope, receive, send)


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
