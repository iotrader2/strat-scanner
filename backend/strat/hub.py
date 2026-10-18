"""One in-process fan-out. Browsers subscribe here; none of them talk to the data vendor."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 15


class Hub:
    def __init__(self) -> None:
        self._clients: set = set()
        self._lock = threading.Lock()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def add(self, ws) -> None:
        with self._lock:
            self._clients.add(ws)

    def discard(self, ws) -> None:
        with self._lock:
            self._clients.discard(ws)

    async def heartbeat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await self._broadcast({"type": "ping", "t": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    async def _broadcast(self, message: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.discard(ws)

    def publish(self, message: dict[str, Any]) -> None:
        if self.loop is None or not self.loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(message), self.loop)
        except RuntimeError:
            log.debug("websocket hub has no running loop", exc_info=True)


hub = Hub()
