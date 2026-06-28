"""CLI du collector iphone-observer (phase 1).

Sous-commandes:
  doctor          verifie les prerequis (trust, Mode developpeur, tunnel)
  info            affiche l'identite du device (lockdown)
  tunnel start    demarre et maintient le tunnel RemoteXPC
  tunnel status   liste les devices vus par tunneld
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .device import (
    NoDeviceError,
    NotTrustedError,
    discover_device,
    read_device_info_usb,
    summarize_info,
)
from .preflight import FAIL, run_preflight, worst_status
from .tunnel import probe_tunnel


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="iphone-observer",
        description="Collector d'observabilite live pour iPhone (sidecar pymobiledevice3).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doctor = sub.add_parser("doctor", help="Verifie les prerequis et s'arrete.")

    p_info = sub.add_parser("info", help="Affiche l'identite du device.")
    p_info.add_argument("--udid", help="UDID cible (defaut: premier device).")
    p_info.add_argument("--wifi", action="store_true", help="Decouverte via tunneld (WiFi).")
    p_info.add_argument("--json", action="store_true", help="Dump brut de all_values.")

    p_tunnel = sub.add_parser("tunnel", help="Gestion du tunnel RemoteXPC.")
    tsub = p_tunnel.add_subparsers(dest="tunnel_cmd", required=True)
    p_tcheck = tsub.add_parser(
        "check", help="Etablit le tunnel userspace (sans root) puis le ferme."
    )
    p_tcheck.add_argument("--udid", help="UDID cible (defaut: premier device).")

    args = parser.parse_args()

    try:
        if args.cmd == "doctor":
            return asyncio.run(_cmd_doctor())
        if args.cmd == "info":
            return asyncio.run(_cmd_info(args))
        if args.cmd == "tunnel" and args.tunnel_cmd == "check":
            return asyncio.run(_cmd_tunnel_check(args))
    except KeyboardInterrupt:
        print("\ninterrompu.", file=sys.stderr)
        return 130
    parser.error("commande inconnue")
    return 2


async def _cmd_doctor() -> int:
    print("Preflight iphone-observer\n")
    checks = await run_preflight()
    for c in checks:
        print(c.line())
    status = worst_status(checks)
    print()
    if status == FAIL:
        print("Resultat: prerequis manquants (voir les fleches ci-dessus).")
        return 1
    print("Resultat: pret a streamer (ou avertissements mineurs).")
    return 0


async def _cmd_info(args: argparse.Namespace) -> int:
    try:
        target = await discover_device(args.udid, wifi=args.wifi)
    except NoDeviceError as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        return 2

    if target.transport == "usb":
        try:
            raw = await read_device_info_usb(target.udid)
        except NotTrustedError as exc:
            print(f"erreur: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(raw, indent=2, ensure_ascii=False, default=str))
            return 0
        info = summarize_info(raw)
    else:
        # Via tunnel: on n'a que l'identite portee par le RSD.
        info = {
            "nom": target.name,
            "modele": target.product_type,
            "version_ios": target.product_version,
            "udid": target.udid,
        }
        if args.json:
            print(json.dumps(info, indent=2, ensure_ascii=False))
            return 0

    print(f"Device ({target.transport})\n")
    width = max(len(k) for k in info)
    for key, value in info.items():
        print(f"  {key.ljust(width)}  {value}")
    return 0


async def _cmd_tunnel_check(args: argparse.Namespace) -> int:
    print("Etablissement du tunnel userspace (sans root)...", file=sys.stderr)
    result = await probe_tunnel(args.udid, timeout_s=30.0)
    if result["ok"]:
        print(result["detail"])
        print("Tunnel OK. Le collector (phase 2) pourra l'ouvrir de la meme facon.")
        return 0
    print(f"erreur: {result['detail']}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
