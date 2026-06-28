"""Analyzer deviceinfo: stockage, apps installees, crashs recents.

Ces infos se lisent via lockdown USB (sans tunnel) et changent lentement: on les
rafraichit periodiquement plutot qu'en flux. Independant du tunnel, comme les
autres analyzers (indexing, storage).

  - storage: capacite/dispo du disque (domaine lockdown com.apple.disk_usage)
  - apps: liste des apps utilisateur (installation_proxy), une fois puis rafraichie
  - crashes: fichiers de rapports recents (.ips), via CrashReportsManager

Resilient: une erreur publie un event `unavailable` puis on retente au cycle
suivant, sans jamais lever (n'affecte pas le collector).
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

from pymobiledevice3.lockdown import create_using_usbmux

from ..events import SOURCE_DEVICEINFO, EventBus

# Date en fin de nom de fichier .ips: AAAA-MM-JJ-HHMMSS
_CRASH_DATE = re.compile(r"-(\d{4}-\d{2}-\d{2})-(\d{6})\.ips$")


async def _read_storage(ld) -> Optional[dict[str, Any]]:
    du = await ld.get_value(domain="com.apple.disk_usage")
    if not isinstance(du, dict):
        return None
    total = du.get("TotalDiskCapacity")
    data_total = du.get("TotalDataCapacity")
    free = du.get("TotalDataAvailable")
    if not isinstance(data_total, (int, float)) or not isinstance(free, (int, float)):
        return None
    return {
        "total_bytes": total,
        "data_total_bytes": data_total,
        "free_bytes": free,
        "used_bytes": max(0, int(data_total) - int(free)),
    }


async def _read_apps(ld) -> Optional[dict[str, Any]]:
    from pymobiledevice3.services.installation_proxy import InstallationProxyService

    ip = InstallationProxyService(ld)
    apps = await ip.get_apps(application_type="User", calculate_sizes=False)
    if not isinstance(apps, dict):
        return None
    rows = []
    for bundle, info in apps.items():
        if not isinstance(info, dict):
            continue
        rows.append({
            "bundle": bundle,
            "name": info.get("CFBundleDisplayName") or info.get("CFBundleName") or bundle,
            "version": info.get("CFBundleShortVersionString") or "",
        })
    rows.sort(key=lambda r: str(r["name"]).lower())
    return {"count": len(rows), "apps": rows}


async def _read_crashes(ld, limit: int = 40) -> Optional[dict[str, Any]]:
    from pymobiledevice3.services.crash_reports import CrashReportsManager

    crm = CrashReportsManager(ld)
    try:
        names = list(await crm.ls())
    finally:
        close = getattr(crm, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                pass
    items = []
    for path in names:
        name = str(path).lstrip("/")
        if not name.endswith(".ips"):
            continue
        m = _CRASH_DATE.search(name)
        if m:
            date = f"{m.group(1)} {m.group(2)[:2]}:{m.group(2)[2:4]}:{m.group(2)[4:6]}"
            process = name[: m.start()]
        else:
            date = ""
            process = name[:-4]
        items.append({"process": process, "date": date, "file": name})
    # La date est au format AAAA-MM-JJ HH:MM:SS: tri lexical = chronologique.
    # Les rapports sans date parsable (date vide) finissent en queue.
    items.sort(key=lambda it: it["date"], reverse=True)
    return {"count": len(items), "items": items[:limit]}


async def run(bus: EventBus, udid: Optional[str] = None, refresh_s: float = 60.0) -> None:
    """Boucle d'enrichissement device info. Apps lues une fois, stockage et
    crashs rafraichis tous les refresh_s."""
    apps_done = False
    while True:
        try:
            ld = await create_using_usbmux(serial=udid)
            try:
                storage = await _read_storage(ld)
                if storage is not None:
                    bus.emit(SOURCE_DEVICEINFO, "storage", storage)
                if not apps_done:
                    apps = await _read_apps(ld)
                    if apps is not None:
                        bus.emit(SOURCE_DEVICEINFO, "apps", apps)
                        apps_done = True
                crashes = await _read_crashes(ld)
                if crashes is not None:
                    bus.emit(SOURCE_DEVICEINFO, "crashes", crashes)
            finally:
                close = getattr(ld, "close", None)
                if close is not None:
                    res = close()
                    if asyncio.iscoroutine(res):
                        await res
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - best-effort, on retente
            bus.emit(SOURCE_DEVICEINFO, "unavailable", {"reason": f"{type(exc).__name__}: {exc}"})
        await asyncio.sleep(refresh_s)
