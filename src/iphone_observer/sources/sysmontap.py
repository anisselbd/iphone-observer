"""Source sysmontap: CPU% / RAM / threads par process, a l'intervalle demande.

Service DVT `com.apple.instruments.server.services.sysmontap`, le meme que le
template "Activity Monitor" d'Instruments. Pattern de subscription repris du
prior art joshuaswanson/ios-activity-monitor (skip de la 1ere frame, qui sert de
reference au calcul de CPU cote device).
"""
from __future__ import annotations

import dataclasses
from typing import Any, Optional

from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap

from ..events import SOURCE_SYSMONTAP, EventBus

# iOS 64 bits utilise des pages de 16 Ko.
_PAGE = 16384


def _build_memory(s: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Stats memoire systeme (pages -> Mo). 'used' = actif + wired + compresse,
    la memoire reellement engagee (le libre est toujours proche de 0 sur iOS)."""
    total = s.get("physMemSize")
    if not isinstance(total, (int, float)) or total <= 0:
        return None

    def mb(pages: Any) -> int:
        # Mo decimaux (pour afficher 12 Go comme Apple, pas 11.4 Gio).
        return round((pages or 0) * _PAGE / 1_000_000)

    active = s.get("vmActiveCount", 0) or 0
    wired = s.get("vmWireCount", 0) or 0
    compressed = s.get("vmCompressorPageCount", 0) or 0
    used = active + wired + compressed
    return {
        "total_mb": mb(total),
        "used_mb": mb(used),
        "free_mb": mb(s.get("vmFreeCount")),
        "active_mb": mb(active),
        "wired_mb": mb(wired),
        "compressed_mb": mb(compressed),
        "inactive_mb": mb(s.get("vmInactiveCount")),
    }


def _normalize(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Transforme une ligne brute sysmontap en sample propre. None si invalide."""
    pid = raw.get("pid")
    if not isinstance(pid, int) or pid < 0:
        return None
    name = raw.get("name") or raw.get("execName") or raw.get("comm") or f"pid {pid}"
    cpu_raw = raw.get("cpuUsage")
    cpu = float(cpu_raw) if isinstance(cpu_raw, (int, float)) else 0.0
    rss = raw.get("physFootprint")
    if not isinstance(rss, int):
        rss = raw.get("memResidentSize") or 0
    threads = raw.get("threadCount") or 0
    return {
        "pid": pid,
        "name": str(name),
        "cpu": round(cpu, 2),
        "rss_mb": round(int(rss) / (1024 * 1024), 1),
        "threads": int(threads),
    }


def _build_tick(samples: list[dict[str, Any]], interval_ms: int) -> dict[str, Any]:
    total_cpu = sum(s["cpu"] for s in samples)
    total_rss = sum(s["rss_mb"] for s in samples)
    top = max(samples, key=lambda s: s["cpu"]) if samples else None
    return {
        "interval_ms": interval_ms,
        "totals": {
            "aggregate_cpu": round(total_cpu, 1),
            "process_count": len(samples),
            "rss_mb_total": round(total_rss, 1),
            "top_name": top["name"] if top else None,
            "top_pid": top["pid"] if top else None,
            "top_cpu": top["cpu"] if top else None,
        },
        "processes": samples,
    }


async def run(rsd, bus: EventBus, interval_ms: int = 1000) -> None:
    """Boucle de subscription. Publie un event `process_tick` par intervalle.

    Leve si le tunnel tombe: le collector relancera la source.
    """
    async with DvtProvider(rsd) as dvt:
        sysmon = await Sysmontap.create(dvt, interval=interval_ms)
        sys_fields = [f.name for f in dataclasses.fields(sysmon.system_attributes_cls)]
        async with sysmon:
            skip_first = True
            last_memory: Optional[dict[str, Any]] = None
            async for row in sysmon:
                # Le flux brut contient aussi des frames non-dict (messages de
                # controle): on les ignore.
                if not isinstance(row, dict):
                    continue
                # System et Processes arrivent dans des frames distinctes: on
                # garde le dernier echantillon memoire vu pour l'attacher au tick.
                sysrow = row.get("System")
                if sysrow is not None:
                    try:
                        last_memory = _build_memory(dict(zip(sys_fields, sysrow)))
                    except Exception:  # noqa: BLE001 - memoire best-effort
                        pass
                if "Processes" not in row:
                    continue
                if skip_first:
                    # La 1ere frame sert de reference au calcul CPU device-side.
                    skip_first = False
                    continue
                entries = [
                    dataclasses.asdict(sysmon.process_attributes_cls(*info))
                    for _pid, info in row["Processes"].items()
                ]
                samples = [s for s in (_normalize(p) for p in entries) if s is not None]
                tick = _build_tick(samples, interval_ms)
                if last_memory is not None:
                    tick["memory"] = last_memory
                bus.emit(SOURCE_SYSMONTAP, "process_tick", tick)
