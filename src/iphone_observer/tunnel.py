"""Cycle de vie du tunnel RemoteXPC (obligatoire sur iOS >= 17, donc iOS 26).

iOS 26 exige un tunnel pour joindre les services DVT / instruments (sysmontap,
diagnostics, networking...). pymobiledevice3 >= 9.30 expose un tunnel "userspace"
**in-process**, sans root: une pile TCP/IP pure Python (PyTCP) remplace
l'interface utun du noyau. C'est le mode retenu ici.

Consequence d'archi: le collector tient le tunnel dans son propre process (pas
de daemon `tunneld` separe, pas de sudo). Un seul process: tunnel + subscribers
+ WebSocket. La reconnexion = reouverture du tunnel.

Repli documente si jamais le mode userspace echoue sur une machine: lancer un
daemon root `sudo pymobiledevice3 remote tunneld` a la main (non gere ici).
"""
from __future__ import annotations

import asyncio
from typing import Optional

from pymobiledevice3.remote.remote_service_discovery import (
    RemoteServiceDiscoveryService,
)


class TunnelError(RuntimeError):
    """Le tunnel RemoteXPC n'a pas pu etre etabli."""


def friendly_tunnel_error(exc: BaseException) -> str:
    """Traduit une erreur d'etablissement de tunnel en message actionnable."""
    raw = str(exc).strip()
    low = raw.lower()
    if "developer mode" in low or "amfi" in low or "developermode" in low:
        return (
            "Mode developpeur desactive sur l'iPhone. Active-le: Reglages > "
            "Confidentialite et securite > Mode developpeur, puis redemarre."
        )
    if "pair" in low or "trust" in low or "escrow" in low:
        return (
            "Appairage tunnel impossible. Deverrouille l'iPhone, tape 'Se fier', "
            "et garde-le deverrouille pendant l'etablissement."
        )
    if "timeout" in low or "timed out" in low:
        return (
            "Etablissement du tunnel en timeout. Verifie que l'iPhone est "
            "deverrouille et joignable (USB ou meme reseau WiFi)."
        )
    if "no such device" in low or "not found" in low or "no device" in low:
        return (
            "Device introuvable pour le tunnel. Branche l'iPhone ou verifie qu'il "
            "est sur le meme reseau."
        )
    return f"Echec du tunnel: {raw or type(exc).__name__}"


class UserspaceTunnel:
    """Tunnel RemoteXPC in-process, sans root (PyTCP). Expose un RSD connecte.

    Usage:
        async with UserspaceTunnel(udid) as rsd:
            ...  # passer rsd aux services DVT
    ou bien open()/close() pour un cycle de vie explicite (collector long-lived).
    """

    def __init__(self, udid: Optional[str] = None, autopair: bool = True) -> None:
        self.udid = udid
        self.autopair = autopair
        self._tunnel = None  # UserspaceRsdTunnel
        self.rsd: Optional[RemoteServiceDiscoveryService] = None

    async def open(self, timeout_s: float = 30.0) -> RemoteServiceDiscoveryService:
        """Etablit le tunnel et renvoie un RSD connecte. Leve TunnelError."""
        if self.rsd is not None:
            return self.rsd
        # Import paresseux: PyTCP n'est touche qu'au moment d'ouvrir le tunnel.
        from pymobiledevice3.remote.userspace_tunnel import UserspaceRsdTunnel

        self._tunnel = UserspaceRsdTunnel(serial=self.udid, autopair=self.autopair)
        try:
            self.rsd = await asyncio.wait_for(self._tunnel.aopen(), timeout=timeout_s)
        except asyncio.TimeoutError as exc:
            await self._safe_close()
            raise TunnelError(
                f"Tunnel non etabli en {timeout_s:.0f}s. "
                "iPhone deverrouille et Mode developpeur actif ?"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - on reclasse en message lisible
            await self._safe_close()
            raise TunnelError(friendly_tunnel_error(exc)) from exc
        return self.rsd

    async def close(self) -> None:
        await self._safe_close()

    async def _safe_close(self, close_timeout_s: float = 3.0) -> None:
        # Particularite pymobiledevice3 9.30: UserspaceRsdTunnel.aclose() peut
        # bloquer plusieurs secondes (le reader PyTCP est parque dans le
        # ThreadPoolExecutor par defaut et ne se reveille pas toujours). On borne
        # la fermeture: au pire les threads daemon mourront a la sortie du
        # process. A revisiter en phase 2 pour la reconnexion a chaud (eviter la
        # fuite de threads sur des cycles repetes).
        if self._tunnel is not None:
            tunnel, self._tunnel = self._tunnel, None
            try:
                await asyncio.wait_for(tunnel.aclose(), timeout=close_timeout_s)
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - best-effort
                pass
        self.rsd = None

    async def __aenter__(self) -> RemoteServiceDiscoveryService:
        return await self.open()

    async def __aexit__(self, *_exc) -> None:
        await self.close()


async def probe_tunnel(udid: Optional[str] = None, timeout_s: float = 30.0) -> dict:
    """Ouvre puis ferme un tunnel pour valider le chemin. Pour le doctor / CLI.

    Renvoie {ok, detail} sans jamais lever: le doctor ne doit pas crasher.
    """
    tunnel = UserspaceTunnel(udid)
    try:
        rsd = await tunnel.open(timeout_s=timeout_s)
        product = getattr(rsd, "product_version", "") or "?"
        name = getattr(rsd, "name", None) or "iPhone"
        return {"ok": True, "detail": f"RSD connecte: {name} (iOS {product})"}
    except TunnelError as exc:
        return {"ok": False, "detail": str(exc)}
    finally:
        await tunnel.close()
