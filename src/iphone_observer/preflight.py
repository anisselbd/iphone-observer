"""Preflight ("doctor"): verifie les prerequis avant de streamer.

iOS 26 impose trois conditions pour les services DVT/instruments:
  1. device appaire (trust) via USB au moins une fois,
  2. Mode developpeur active sur l'iPhone,
  3. tunnel RemoteXPC up.

Chaque check est isole: une erreur ne fait pas tomber les autres, et chaque
echec porte une consigne actionnable. On ne fabrique jamais de statut: si on ne
peut pas determiner, c'est "unknown", pas "ok".
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Optional

from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.usbmux import list_devices

from .device import NotTrustedError, _close_maybe_async, read_device_info_usb
from .tunnel import probe_tunnel

OK = "ok"
FAIL = "fail"
WARN = "warn"
UNKNOWN = "unknown"

_GLYPH = {OK: "[ok]", FAIL: "[X]", WARN: "[!]", UNKNOWN: "[?]"}


@dataclass(slots=True)
class Check:
    name: str
    status: str
    detail: str = ""
    hint: str = ""

    def line(self) -> str:
        base = f"{_GLYPH.get(self.status, '[?]')} {self.name}"
        if self.detail:
            base += f": {self.detail}"
        if self.hint and self.status in (FAIL, WARN, UNKNOWN):
            base += f"\n      -> {self.hint}"
        return base


def _check_python() -> Check:
    v = sys.version_info
    label = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= (3, 14):
        return Check("Python", OK, f"{label} (tunnel userspace dispo, sans root)")
    return Check(
        "Python",
        WARN,
        label,
        "Python < 3.14: le tunnel userspace n'est pas dispo, il faudra "
        "`sudo pymobiledevice3 remote tunneld`.",
    )


async def _check_usb() -> tuple[Check, Optional[str]]:
    try:
        devices = await list_devices()
    except Exception as exc:  # noqa: BLE001
        return Check("Connexion USB", UNKNOWN, str(exc),
                     "usbmux indisponible. usbmuxd tourne-t-il (Finder/Xcode)?"), None
    if not devices:
        return Check(
            "Connexion USB", WARN, "aucun device en USB",
            "Branche l'iPhone (le WiFi reste possible si tunneld le voit deja).",
        ), None
    serial = devices[0].serial
    return Check("Connexion USB", OK, f"{len(devices)} device(s), cible {serial}"), serial


async def _check_trust(serial: Optional[str]) -> tuple[Check, dict]:
    if serial is None:
        return Check("Appairage (trust)", UNKNOWN, "pas de device USB a tester"), {}
    try:
        info = await read_device_info_usb(serial)
    except NotTrustedError as exc:
        return Check("Appairage (trust)", FAIL, str(exc),
                     "Deverrouille l'iPhone et tape 'Se fier'."), {}
    except Exception as exc:  # noqa: BLE001
        return Check("Appairage (trust)", UNKNOWN, str(exc)), {}
    name = info.get("DeviceName", "iPhone")
    ios = info.get("ProductVersion", "?")
    return Check("Appairage (trust)", OK, f"{name}, iOS {ios}"), info


async def _check_developer_mode(serial: Optional[str]) -> Check:
    if serial is None:
        return Check("Mode developpeur", UNKNOWN, "pas de device USB a tester")
    client = None
    try:
        client = await create_using_usbmux(serial=serial)
        # iOS 16+: statut expose via le domaine amfi. get_value est une coroutine
        # dans pymobiledevice3 >= 9.30.
        status = await client.get_value(
            "com.apple.security.mac.amfi", "DeveloperModeStatus"
        )
        if status is True:
            return Check("Mode developpeur", OK, "active")
        if status is False:
            return Check(
                "Mode developpeur", FAIL, "desactive",
                "Reglages > Confidentialite et securite > Mode developpeur, "
                "puis redemarre l'iPhone.",
            )
        return Check("Mode developpeur", UNKNOWN, f"reponse inattendue: {status!r}")
    except Exception as exc:  # noqa: BLE001
        return Check(
            "Mode developpeur", UNKNOWN, str(exc),
            "Verifie a la main: Reglages > Confidentialite et securite > Mode developpeur.",
        )
    finally:
        if client is not None:
            await _close_maybe_async(client)


async def _check_tunnel(devmode_ok: bool, udid: Optional[str]) -> Check:
    # Le tunnel userspace exige le Mode developpeur. Inutile (et lent) de sonder
    # tant qu'il est off: on a deja signale la cause en amont.
    if not devmode_ok:
        return Check(
            "Tunnel RemoteXPC", UNKNOWN, "non teste",
            "Active le Mode developpeur puis relance `iphone-observer doctor`.",
        )
    # Le chemin nominal etablit le tunnel en ~1s; 12s couvre large sans figer le
    # doctor si le device est en veille ou en train de redemarrer.
    result = await probe_tunnel(udid, timeout_s=12.0)
    if result["ok"]:
        return Check("Tunnel RemoteXPC", OK, result["detail"])
    return Check(
        "Tunnel RemoteXPC", FAIL, result["detail"],
        "Tunnel userspace (sans root) injoignable. iPhone deverrouille ?",
    )


async def run_preflight() -> list[Check]:
    """Execute tous les checks. Ordre: env -> USB -> trust -> devmode -> tunnel."""
    checks: list[Check] = [_check_python()]
    usb_check, serial = await _check_usb()
    checks.append(usb_check)
    trust_check, info = await _check_trust(serial)
    checks.append(trust_check)
    devmode = await _check_developer_mode(serial)
    checks.append(devmode)
    udid = info.get("UniqueDeviceID", serial) if info else serial
    checks.append(await _check_tunnel(devmode.status == OK, udid))
    return checks


def worst_status(checks: list[Check]) -> str:
    order = [OK, UNKNOWN, WARN, FAIL]
    worst = OK
    for c in checks:
        if order.index(c.status) > order.index(worst):
            worst = c.status
    return worst
