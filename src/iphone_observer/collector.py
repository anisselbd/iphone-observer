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

from .analyzers import deviceinfo, indexing
from .device import discover_device
from .events import SOURCE_COLLECTOR, EventBus
from .sources import diagnostics, display, graphics, networking, syslog, sysmontap
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
        self._cpu_cores: Optional[int] = None
        self._device_data: dict = {}
        self._rsd = None  # RSD du tunnel courant, pour les actions a la demande

    # --- cycle de vie ---------------------------------------------------------

    async def start(self) -> None:
        self._stop.clear()
        # Taches longues, abonnees au bus, independantes du tunnel.
        self._analyzer_tasks = [
            asyncio.create_task(indexing.run(self.bus), name="analyzer:indexing"),
            asyncio.create_task(
                deviceinfo.run(self.bus, self.udid), name="analyzer:deviceinfo"
            ),
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
        self._device_data = {
            "udid": target.udid,
            "name": target.name,
            "model": target.product_type,
            "ios": target.product_version,
            "transport": target.transport,
        }
        self.bus.emit(SOURCE_COLLECTOR, "device", dict(self._device_data))

    async def _fetch_hardware(self, rsd) -> None:
        """Recupere le nombre de coeurs CPU (une fois) et re-emet l'identite
        enrichie. Best-effort: le dashboard a un defaut si ca echoue."""
        from pymobiledevice3.services.dvt.instruments.device_info import DeviceInfo
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider

        try:
            async with DvtProvider(rsd) as dvt:
                async with DeviceInfo(dvt) as di:
                    hw = await di.hardware_information()
            cores = hw.get("numberOfCpus")
            if isinstance(cores, int) and cores > 0:
                self._cpu_cores = cores
                if self._device_data:
                    self.bus.emit(
                        SOURCE_COLLECTOR, "device",
                        {**self._device_data, "cpu_cores": cores},
                    )
        except Exception:  # noqa: BLE001
            pass

    async def _run(self) -> None:
        await self._resolve_identity()
        backoff = 1.0
        while not self._stop.is_set():
            try:
                self._set_state("connecting")
                rsd = await self._tunnel.open()
                self._rsd = rsd
                self._set_state("connected")
                backoff = 1.0
                if self._cpu_cores is None:
                    await self._fetch_hardware(rsd)
                await self._run_sources(rsd)
            except asyncio.CancelledError:
                raise
            except TunnelError as exc:
                self._emit_error("tunnel", str(exc))
            except Exception as exc:  # noqa: BLE001 - on reconnecte, jamais de crash
                self._emit_error("collector", f"{type(exc).__name__}: {exc}")
            finally:
                self._rsd = None
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
            # Sources auxiliaires auto-resilientes (ne font pas reconnecter le tout
            # si leur service refuse): GPU/FPS (channel OpenGL) et info ecran live
            # (CoreDevice, vrai taux ProMotion + etat retroeclairage).
            ("graphics", graphics.run, {}),
            ("display", display.run, {}),
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

    # --- actions a la demande -------------------------------------------------

    async def take_screenshot(self) -> bytes:
        """Capture l'ecran via le tunnel courant (PNG). Leve si pas connecte."""
        rsd = self._rsd
        if rsd is None:
            raise RuntimeError("tunnel non connecte: capture impossible pour l'instant.")
        from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
        from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot

        async with DvtProvider(rsd) as dvt:
            async with Screenshot(dvt) as sc:
                return await sc.get_screenshot()

    async def _sleep_or_stop(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
