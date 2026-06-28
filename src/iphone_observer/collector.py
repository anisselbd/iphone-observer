"""Collector: possede le tunnel, lance N sources concurrentes, supervise et
reconnecte automatiquement.

Boucle de vie:
  connecting -> connected -> (coupure) -> reconnecting -> connecting ...

Une coupure (USB debranche, tel en veille, perte de tunnel) fait remonter une
exception depuis une source; le collector ferme le tunnel, publie l'etat, attend
un backoff, puis retente. Jamais de crash silencieux: chaque transition et
chaque erreur est un event sur le bus.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from .analyzers import indexing
from .device import discover_device
from .events import SOURCE_COLLECTOR, EventBus
from .sources import diagnostics, networking, syslog, sysmontap
from .storage import Storage
from .tunnel import TunnelError, UserspaceTunnel

# Une source: coroutine run(rsd, bus, **opts). On la relance a chaque tunnel.
SourceRun = Callable[..., Awaitable[None]]


class Collector:
    def __init__(
        self,
        udid: Optional[str] = None,
        interval_ms: int = 1000,
        battery_interval_s: float = 10.0,
        db_path: Optional[str] = "data/iphone-observer.sqlite",
    ) -> None:
        self.udid = udid
        self.interval_ms = interval_ms
        self.battery_interval_s = battery_interval_s
        self.bus = EventBus(udid=udid or "")
        self.state = "starting"
        self.storage: Optional[Storage] = Storage(db_path) if db_path else None
        self._tunnel = UserspaceTunnel(udid)
        self._task: Optional[asyncio.Task] = None
        self._analyzer_tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    # --- cycle de vie ---------------------------------------------------------

    async def start(self) -> None:
        self._stop.clear()
        # Taches longues, abonnees au bus, independantes du tunnel.
        self._analyzer_tasks = [
            asyncio.create_task(indexing.run(self.bus), name="analyzer:indexing"),
        ]
        if self.storage is not None:
            await self.storage.open()
            self._analyzer_tasks.append(
                asyncio.create_task(self.storage.run(self.bus), name="storage")
            )
        self._task = asyncio.create_task(self._run(), name="collector")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        for t in self._analyzer_tasks:
            t.cancel()
        if self._analyzer_tasks:
            await asyncio.gather(*self._analyzer_tasks, return_exceptions=True)
            self._analyzer_tasks = []
        if self.storage is not None:
            await self.storage.close()
        await self._tunnel.close()
        self._set_state("stopped")

    # --- etat -----------------------------------------------------------------

    def _set_state(self, state: str, detail: str = "") -> None:
        self.state = state
        self.bus.emit(SOURCE_COLLECTOR, "status", {"state": state, "detail": detail})

    def _emit_error(self, scope: str, message: str) -> None:
        self.bus.emit(SOURCE_COLLECTOR, "error", {"scope": scope, "message": message})

    # --- boucle de supervision ------------------------------------------------

    async def _resolve_identity(self) -> None:
        """Resout l'identite du device (USB) une fois, pour l'afficher. Best-effort."""
        try:
            target = await discover_device(self.udid)
        except Exception as exc:  # noqa: BLE001
            self._emit_error("device", f"identite indisponible: {exc}")
            return
        if not self.udid:
            self.udid = target.udid
        self.bus.udid = target.udid
        self.bus.emit(SOURCE_COLLECTOR, "device", {
            "udid": target.udid,
            "name": target.name,
            "model": target.product_type,
            "ios": target.product_version,
            "transport": target.transport,
        })

    async def _run(self) -> None:
        await self._resolve_identity()
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._set_state("connecting")
                rsd = await self._tunnel.open()
                self._set_state("connected")
                backoff = 1.0
                await self._run_sources(rsd)
            except asyncio.CancelledError:
                raise
            except TunnelError as exc:
                self._emit_error("tunnel", str(exc))
            except Exception as exc:  # noqa: BLE001 - on reconnecte, jamais de crash
                self._emit_error("collector", f"{type(exc).__name__}: {exc}")
            finally:
                await self._tunnel.close()

            if self._stop.is_set():
                break
            self._set_state("reconnecting", f"nouvelle tentative dans {backoff:.0f}s")
            await self._sleep_or_stop(backoff)
            backoff = min(backoff * 2, 15.0)

    async def _run_sources(self, rsd) -> None:
        """Lance toutes les sources. Rend la main (en levant) des qu'une source
        s'arrete ou echoue, pour declencher une reconnexion complete."""
        specs: list[tuple[str, SourceRun, dict]] = [
            ("sysmontap", sysmontap.run, {"interval_ms": self.interval_ms}),
            ("diagnostics", diagnostics.run, {"interval_s": self.battery_interval_s}),
            ("syslog", syslog.run, {}),
            ("networking", networking.run, {}),
        ]
        tasks = [
            asyncio.create_task(run(rsd, self.bus, **opts), name=f"source:{name}")
            for name, run, opts in specs
        ]
        stop_task = asyncio.create_task(self._stop.wait(), name="stop-watch")
        try:
            done, _pending = await asyncio.wait(
                [*tasks, stop_task], return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for t in tasks:
                t.cancel()
            stop_task.cancel()
            await asyncio.gather(*tasks, stop_task, return_exceptions=True)

        if self._stop.is_set():
            return
        # Une source s'est arretee: on propage pour reconnecter.
        for t in tasks:
            if t in done and not t.cancelled():
                exc = t.exception()
                if exc is not None:
                    raise exc
        raise TunnelError("une source s'est arretee (flux interrompu)")

    async def _sleep_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
