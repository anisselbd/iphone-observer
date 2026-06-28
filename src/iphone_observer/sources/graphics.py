"""Source graphics: GPU et FPS systeme via le channel Instruments OpenGL.

Service DVT `com.apple.instruments.server.services.graphics.opengl`, qui remonte
l'utilisation du GPU (Device/Renderer/Tiler), les FPS Core Animation et la
memoire GPU. Valeurs reelles cote device, non fabriquees.

Source auxiliaire: si le service refuse de demarrer, on publie un event
`unavailable` et on se met en veille au lieu de faire reconnecter tout le
collector. La premiere frame (FPS=0) sert de warmup et est ignoree.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.graphics import Graphics

from ..events import SOURCE_GRAPHICS, EventBus


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) else None


def _build(ev: dict[str, Any]) -> dict[str, Any]:
    """Extrait les metriques utiles d'un echantillon graphics."""
    return {
        "gpu_util": _num(ev.get("Device Utilization %")),
        "renderer_util": _num(ev.get("Renderer Utilization %")),
        "tiler_util": _num(ev.get("Tiler Utilization %")),
        "fps": _num(ev.get("CoreAnimationFramesPerSecond")),
        "gpu_mem_inuse": _num(ev.get("In use system memory")),
        "gpu_mem_alloc": _num(ev.get("Alloc system memory")),
        "recovery_count": _num(ev.get("recoveryCount")),
    }


async def run(rsd, bus: EventBus) -> None:
    """Boucle de subscription graphics. Auto-resiliente: ne propage pas un refus
    de service (n'entraine pas de reconnexion globale), se met en veille."""
    try:
        async with DvtProvider(rsd) as dvt:
            async with Graphics(dvt) as gfx:
                first = True
                async for ev in gfx:
                    if not isinstance(ev, dict):
                        continue
                    if first:
                        # 1ere frame de warmup (FPS a 0): on la saute.
                        first = False
                        continue
                    bus.emit(SOURCE_GRAPHICS, "sample", _build(ev))
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - source auxiliaire
        bus.emit(
            SOURCE_GRAPHICS, "unavailable",
            {"reason": f"{type(exc).__name__}: {exc}"},
        )
        # On reste en vie (sans flux) pour ne pas declencher de reconnexion.
        await asyncio.Event().wait()
