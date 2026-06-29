"""Source display: info ecran live via CoreDevice getdisplayinfo.

Remonte le vrai taux de rafraichissement (jusqu'a 120 Hz ProMotion), la
resolution native, le gamut, et l'etat du retroeclairage. Contrairement a la
jauge FPS legacy (graphics.opengl, plafonnee a 60), refreshRate ici est le vrai
mode du panneau.

Le retroeclairage change souvent (ecran allume/eteint): on interroge
periodiquement. Source auxiliaire resiliente: une erreur ne fait pas reconnecter
le collector.

Valeurs observees du backlightState: "activeOn" (ecran allume), "off" (eteint).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from pymobiledevice3.remote.core_device.device_info import DeviceInfoService

from ..events import SOURCE_COLLECTOR, EventBus


def parse_display_info(info: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Extrait les infos de l'ecran principal d'une reponse getdisplayinfo."""
    displays = info.get("displays", []) if isinstance(info, dict) else []
    primary = next((d for d in displays if d.get("primary")), None)
    if not primary:
        return None
    mode = primary.get("currentMode", {}) or {}
    native = primary.get("nativeSize") or [0, 0]
    rate = mode.get("refreshRate")
    return {
        "refresh_rate": rate,
        "native_width": int(native[0]) if len(native) > 0 else None,
        "native_height": int(native[1]) if len(native) > 1 else None,
        "color_gamut": mode.get("colorGamut"),
        "hdr_mode": mode.get("hdrMode"),
        "scale": mode.get("preferredUIScale") or primary.get("pointScale"),
        "backlight": info.get("backlightState"),
        "promotion": isinstance(rate, (int, float)) and rate >= 90,
    }


async def run(rsd, bus: EventBus, interval_s: float = 3.0) -> None:
    """Interroge l'ecran toutes les interval_s. Auto-resiliente."""
    try:
        while True:
            try:
                async with DeviceInfoService(rsd) as svc:
                    info = await svc.get_display_info()
                data = parse_display_info(info)
                if data is not None:
                    bus.emit(SOURCE_COLLECTOR, "display", data)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - best-effort, on reessaie
                pass
            await asyncio.sleep(interval_s)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - ne pas faire reconnecter le tout
        bus.emit(SOURCE_COLLECTOR, "display_error", {"reason": f"{type(exc).__name__}: {exc}"})
        await asyncio.Event().wait()
