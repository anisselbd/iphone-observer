"""Detecteur d'etat d'indexation (analyzer).

Signal robuste et quantitatif: le CPU cumule des daemons d'indexation / analyse
on-device, lu sur le flux sysmontap (pas de parsing de chaines de log fragile).
Hysteresis pour ne pas clignoter: on bascule "en cours" des qu'ils chauffent, et
"terminee" seulement apres un calme prolonge.

Etats: "indexing" (en cours), "idle" (terminee/calme), "unknown" (pas encore
assez d'observation).
"""
from __future__ import annotations

import asyncio
import time

from ..events import SOURCE_ANALYZER, SOURCE_SYSMONTAP, EventBus

# Daemons surveilles (les 4 du brief + cousins proches d'indexation).
INDEXING_DAEMONS = {
    "photoanalysisd",
    "mediaanalysisd",
    "corespotlightd",
    "cloudd",
    "photolibraryd",
    "spotlightknowledged",
    "spotlightknowledged.updater",
}


async def run(
    bus: EventBus,
    active_cpu_threshold: float = 8.0,
    quiet_seconds: float = 45.0,
    heartbeat_s: float = 5.0,
) -> None:
    """Boucle d'analyse. Tourne tant que le collector vit (independant du tunnel)."""
    queue = bus.subscribe()
    start = time.monotonic()
    state = "unknown"
    last_active_at: float | None = None
    last_emit = 0.0
    try:
        while True:
            payload = await queue.get()
            if payload.get("source") != SOURCE_SYSMONTAP or payload.get("type") != "process_tick":
                continue
            now = time.monotonic()
            procs = payload.get("data", {}).get("processes", [])
            daemons = sorted(
                (
                    {"name": p["name"], "pid": p["pid"], "cpu": p["cpu"]}
                    for p in procs
                    if p["name"] in INDEXING_DAEMONS and p["cpu"] >= 0.5
                ),
                key=lambda d: d["cpu"],
                reverse=True,
            )
            total = round(sum(d["cpu"] for d in daemons), 1)
            active_now = total >= active_cpu_threshold

            if active_now:
                last_active_at = now
                new_state = "indexing"
            elif last_active_at is not None and now - last_active_at >= quiet_seconds:
                new_state = "idle"
            elif last_active_at is None and now - start >= quiet_seconds:
                new_state = "idle"
            elif state == "unknown":
                new_state = "unknown"
            else:
                # Fenetre de grace: on reste "indexing" pendant le refroidissement.
                new_state = state

            quiet_for = round(now - (last_active_at if last_active_at else start))
            changed = new_state != state
            state = new_state

            if changed or now - last_emit >= heartbeat_s:
                last_emit = now
                bus.emit(SOURCE_ANALYZER, "indexing", {
                    "state": state,
                    "active_now": active_now,
                    "active_cpu": total,
                    "daemons": daemons[:6],
                    "quiet_for_s": quiet_for,
                    "threshold_cpu": active_cpu_threshold,
                })
    except asyncio.CancelledError:
        raise
    finally:
        bus.unsubscribe(queue)
