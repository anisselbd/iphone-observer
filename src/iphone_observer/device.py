"""Decouverte et identite du device (phase 1).

La lecture de l'identite (device info) passe par lockdown et fonctionne en USB
sans tunnel. Le tunnel RemoteXPC n'est requis que pour les services DVT /
instruments (sysmontap, networking, energy), traites a partir de la phase 2.

Patterns de decouverte repris du prior art joshuaswanson/ios-activity-monitor
(ne pas reinventer), adaptes pour exposer l'identite complete du device.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

from pymobiledevice3.exceptions import TunneldConnectionError
from pymobiledevice3.lockdown import create_using_usbmux
from pymobiledevice3.tunneld.api import (
    get_tunneld_device_by_udid,
    get_tunneld_devices,
)
from pymobiledevice3.usbmux import list_devices


class NoDeviceError(RuntimeError):
    """Aucun device joignable (ni USB, ni tunnel)."""


class NotTrustedError(RuntimeError):
    """Le device est branche mais l'appairage (trust) n'est pas etabli."""


@dataclass(slots=True)
class DeviceTarget:
    """Identite minimale d'un device, suffisante pour cibler les services."""

    udid: str
    name: str
    product_type: str
    product_version: str
    transport: str  # "usb" ou "tunneld"


# Champs lockdown qu'on remonte en clair dans `device info`. La valeur brute
# complete reste accessible via --json.
_INFO_KEYS: dict[str, str] = {
    "DeviceName": "nom",
    "ProductType": "modele",
    "ProductVersion": "version_ios",
    "BuildVersion": "build",
    "UniqueDeviceID": "udid",
    "SerialNumber": "serie",
    "HardwareModel": "hardware_model",
    "CPUArchitecture": "cpu_arch",
    "DeviceColor": "couleur",
    "DeviceEnclosureColor": "couleur_chassis",
    "WiFiAddress": "wifi_mac",
    "BluetoothAddress": "bluetooth_mac",
    "TimeZone": "fuseau",
    "ProductName": "produit",
}


async def _close_maybe_async(obj: Any) -> None:
    """close() est tantot sync, tantot coroutine selon le transport."""
    close = getattr(obj, "close", None)
    if close is None:
        return
    result = close()
    if asyncio.iscoroutine(result):
        await result


async def discover_device(
    preferred_udid: Optional[str] = None, wifi: bool = False
) -> DeviceTarget:
    """Trouve un device cible. USB d'abord, repli sur le tunnel (WiFi)."""
    if wifi:
        return await _discover_via_tunneld(preferred_udid)

    devices = await list_devices()
    if not devices:
        try:
            return await _discover_via_tunneld(preferred_udid)
        except NoDeviceError:
            raise NoDeviceError(
                "Aucun iPhone detecte en USB ni via le tunnel developpeur. "
                "Branche le cable (ou, en WiFi, verifie que tunneld a decouvert "
                "le device et que le tel est deverrouille)."
            )

    if preferred_udid is not None:
        for dev in devices:
            if dev.matches_udid(preferred_udid):
                return await _target_from_usb(dev.serial)
        try:
            return await _discover_via_tunneld(preferred_udid)
        except NoDeviceError:
            raise NoDeviceError(f"UDID {preferred_udid} non connecte.")

    return await _target_from_usb(devices[0].serial)


async def _target_from_usb(serial: str) -> DeviceTarget:
    info = await read_device_info_usb(serial)
    return DeviceTarget(
        udid=info.get("UniqueDeviceID", serial),
        name=info.get("DeviceName", "iPhone"),
        product_type=info.get("ProductType", ""),
        product_version=info.get("ProductVersion", ""),
        transport="usb",
    )


async def _discover_via_tunneld(preferred_udid: Optional[str]) -> DeviceTarget:
    try:
        if preferred_udid is not None:
            rsd = await get_tunneld_device_by_udid(preferred_udid)
            if rsd is None:
                raise NoDeviceError(
                    f"UDID {preferred_udid} introuvable dans tunneld. "
                    "Verifie que tunneld tourne et que le device est joignable."
                )
        else:
            devices = await get_tunneld_devices()
            if not devices:
                raise NoDeviceError(
                    "tunneld ne suit aucun device. Verifie: meme reseau WiFi, "
                    "Mode developpeur active, et appairage USB fait au moins une fois."
                )
            rsd = devices[0]
    except TunneldConnectionError as exc:
        raise NoDeviceError(
            "tunneld n'est pas lance. Demarre-le avec:\n"
            "  iphone-observer tunnel start\n"
            "ou directement:\n"
            "  pymobiledevice3 remote tunneld --userspace"
        ) from exc

    try:
        return DeviceTarget(
            udid=rsd.udid,
            name=getattr(rsd, "name", None) or "iPhone",
            product_type=getattr(rsd, "product_type", ""),
            product_version=getattr(rsd, "product_version", ""),
            transport="tunneld",
        )
    finally:
        await _close_maybe_async(rsd)


async def read_device_info_usb(serial: Optional[str] = None) -> dict[str, Any]:
    """Lit le dictionnaire lockdown complet (all_values) en USB.

    Leve NotTrustedError si l'appairage n'est pas etabli.
    """
    try:
        client = await create_using_usbmux(serial=serial)
    except Exception as exc:  # noqa: BLE001 - on reclasse en erreur lisible
        msg = str(exc).lower()
        if "pair" in msg or "trust" in msg or "escrow" in msg:
            raise NotTrustedError(
                "Device non appaire. Deverrouille l'iPhone et tape 'Se fier' a "
                "l'invite, puis reessaie."
            ) from exc
        raise
    try:
        return dict(client.all_values)
    finally:
        await _close_maybe_async(client)


def summarize_info(raw: dict[str, Any]) -> dict[str, Any]:
    """Extrait les champs lisibles de all_values pour l'affichage."""
    out: dict[str, Any] = {}
    for key, label in _INFO_KEYS.items():
        if key in raw and raw[key] not in (None, ""):
            out[label] = raw[key]
    return out
