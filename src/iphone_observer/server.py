"""Serveur WebSocket: demarre le collector et diffuse le bus d'events.

Le collector (qui tient le tunnel GPL pymobiledevice3) tourne dans CE process.
L'UI (dashboard web phase 1, shell natif phase 2) ne parle au collector que par
ce WebSocket, jamais par import direct: la frontiere de licence est nette.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .collector import Collector

STATIC_DIR = Path(__file__).parent / "static"


def make_app(udid: Optional[str] = None, interval_ms: int = 1000) -> FastAPI:
    collector = Collector(udid=udid, interval_ms=interval_ms)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await collector.start()
        try:
            yield
        finally:
            await collector.stop()

    app = FastAPI(lifespan=lifespan, title="iphone-observer")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/snapshot")
    async def snapshot() -> dict:
        return {
            "type": "snapshot",
            "state": collector.state,
            "udid": collector.udid or "",
            "events": collector.bus.snapshot(),
        }

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        queue = collector.bus.subscribe()
        try:
            # Amorce: etat courant + dernier event connu par (source, type).
            await websocket.send_text(json.dumps({
                "type": "hello",
                "state": collector.state,
                "udid": collector.udid or "",
                "events": collector.bus.snapshot(),
            }))
            while True:
                payload = await queue.get()
                await websocket.send_text(json.dumps(payload))
        except WebSocketDisconnect:
            return
        except (asyncio.CancelledError, Exception):
            return
        finally:
            collector.bus.unsubscribe(queue)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
