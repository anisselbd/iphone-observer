"""Source diagnostics: telemetrie batterie / hardware en polling.

Service `com.apple.mobile.diagnostics_relay` -> IORegistry `IOPMPowerSource`
(le meme que `get_battery`). Donne temperature, voltage, amperage, cycles de
charge, capacite design vs actuelle, etat de charge.

Note honnete: l'etat thermique systeme (nominal/fair/serious/critical) n'est pas
expose proprement par ce service sur iOS 26; on remonte la temperature batterie
comme indicateur, sans fabriquer un etat thermique qu'on n'a pas. mobilegestalt
est deprecie depuis iOS 17.4, on ne l'utilise pas.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from pymobiledevice3.services.diagnostics import DiagnosticsService

from ..events import SOURCE_DIAGNOSTICS, EventBus


def _num(raw: dict[str, Any], key: str) -> Optional[float]:
    v = raw.get(key)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _adapter(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    det = raw.get("AdapterDetails")
    if not isinstance(det, dict):
        return None
    watts = det.get("Watts")
    desc = det.get("Description") or det.get("Name")
    if watts is None and desc is None:
        return None
    return {"watts": watts, "description": desc}


def normalize_battery(raw: dict[str, Any]) -> dict[str, Any]:
    """Mappe IOPMPowerSource vers des unites lisibles. Aucune valeur fabriquee:
    un champ absent reste None."""
    temp = _num(raw, "Temperature")
    vtemp = _num(raw, "VirtualTemperature")
    voltage = _num(raw, "Voltage")
    instant_a = _num(raw, "InstantAmperage")
    amperage = instant_a if instant_a is not None else _num(raw, "Amperage")
    design = _num(raw, "DesignCapacity")
    full = _num(raw, "AppleRawMaxCapacity")
    nominal = _num(raw, "NominalChargeCapacity")
    health = round(100 * full / design, 1) if (full and design) else None
    time_rem = _num(raw, "TimeRemaining")
    # TimeRemaining vaut 0 ou 65535 quand non significatif (branche/plein).
    if time_rem in (0, 65535):
        time_rem = None

    return {
        "level_pct": _num(raw, "CurrentCapacity"),
        "is_charging": raw.get("IsCharging"),
        "external_connected": raw.get("ExternalConnected"),
        "fully_charged": raw.get("FullyCharged"),
        "temperature_c": round(temp / 100, 1) if temp is not None else None,
        "virtual_temperature_c": round(vtemp / 100, 1) if vtemp is not None else None,
        "voltage_v": round(voltage / 1000, 3) if voltage is not None else None,
        "amperage_ma": int(amperage) if amperage is not None else None,
        "cycle_count": _num(raw, "CycleCount"),
        "design_capacity_mah": design,
        "full_capacity_mah": full,
        "nominal_capacity_mah": nominal,
        "health_pct": health,
        "time_remaining_min": time_rem,
        "serial": raw.get("Serial"),
        "adapter": _adapter(raw),
    }


async def run(rsd, bus: EventBus, interval_s: float = 10.0) -> None:
    """Boucle de polling batterie. Leve si le service tombe (le collector
    reconnecte)."""
    svc = DiagnosticsService(rsd)
    while True:
        raw = await svc.get_battery()
        bus.emit(SOURCE_DIAGNOSTICS, "battery", normalize_battery(raw or {}))
        await asyncio.sleep(interval_s)
