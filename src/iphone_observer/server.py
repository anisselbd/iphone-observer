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
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .collector import Collector

STATIC_DIR = Path(__file__).parent / "static"


def make_app(
    udid: Optional[str] = None,
    interval_ms: int = 1000,
    db_path: Optional[str] = "data/iphone-observer.sqlite",
) -> FastAPI:
    collector = Collector(udid=udid, interval_ms=interval_ms, db_path=db_path)

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

    @app.get("/api/timeline")
    async def timeline(minutes: float = 10.0) -> dict:
        if collector.storage is None:
            return {"available": False, "reason": "storage desactive"}
        return await collector.storage.timeline(minutes=minutes)

    @app.get("/api/export.csv")
    async def export_csv(minutes: float = 60.0) -> Response:
        if collector.storage is None:
            return JSONResponse(status_code=503, content={"error": "storage desactive"})
        rep = await collector.storage.report(minutes=minutes, udid=collector.udid or "")
        if not rep.get("available"):
            return JSONResponse(status_code=503, content={"error": rep.get("reason", "indisponible")})
        return Response(
            content=rep["csv"], media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=iphone-observer-session.csv"},
        )

    @app.get("/api/export.md")
    async def export_md(minutes: float = 60.0) -> Response:
        if collector.storage is None:
            return JSONResponse(status_code=503, content={"error": "storage desactive"})
        rep = await collector.storage.report(minutes=minutes, udid=collector.udid or "")
        if not rep.get("available"):
            return JSONResponse(status_code=503, content={"error": rep.get("reason", "indisponible")})
        return Response(
            content=rep["summary"], media_type="text/markdown",
            headers={"Content-Disposition": "attachment; filename=iphone-observer-session.md"},
        )

    @app.get("/api/screenshot")
    async def screenshot() -> Response:
        try:
            png = await collector.take_screenshot()
        except Exception as exc:  # noqa: BLE001 - on renvoie une erreur lisible
            return JSONResponse(
                status_code=503,
                content={"error": f"{type(exc).__name__}: {exc}"},
            )
        return Response(content=png, media_type="image/png")

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
