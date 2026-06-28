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
import os
import sys

from pymobiledevice3.exceptions import StartServiceError

from .device import (
    NoDeviceError,
    NotTrustedError,
    discover_device,
    read_device_info_usb,
    summarize_info,
)
from .preflight import FAIL, run_preflight, worst_status
from .tunnel import TunnelError, UserspaceTunnel, probe_tunnel


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

    p_serve = sub.add_parser(
        "serve", help="Lance le collector (tunnel + sysmontap) et le dashboard web."
    )
    p_serve.add_argument("--udid", help="UDID cible (defaut: premier device).")
    p_serve.add_argument(
        "--interval", type=int, default=1000, help="Intervalle sysmontap en ms (defaut: 1000)."
    )
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (defaut: 127.0.0.1).")
    p_serve.add_argument("--port", type=int, default=8765, help="Bind port (defaut: 8765).")

    p_cap = sub.add_parser(
        "capture", help="Sniffe le trafic brut vers un fichier .pcap (pcapng)."
    )
    p_cap.add_argument("--out", "-o", default="capture.pcapng", help="Fichier de sortie.")
    p_cap.add_argument("--count", "-c", type=int, default=200, help="Nombre de paquets (defaut: 200).")
    p_cap.add_argument("--process", help="Filtre par nom de process ou pid.")
    p_cap.add_argument("--iface", help="Filtre par interface (ex: en0, pdp_ip0).")
    p_cap.add_argument("--udid", help="UDID cible (defaut: premier device).")

    args = parser.parse_args()

    try:
        if args.cmd == "doctor":
            return asyncio.run(_cmd_doctor())
        if args.cmd == "info":
            return asyncio.run(_cmd_info(args))
        if args.cmd == "tunnel" and args.tunnel_cmd == "check":
            return asyncio.run(_cmd_tunnel_check(args))
        if args.cmd == "serve":
            return _cmd_serve(args)
        if args.cmd == "capture":
            return _cmd_capture(args)
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


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import make_app

    app = make_app(udid=args.udid, interval_ms=args.interval)
    url = f"http://{args.host}:{args.port}"
    print(f"Collector + dashboard: {url}", file=sys.stderr)
    print("Le tunnel et sysmontap demarrent au premier chargement. Ctrl-C pour arreter.",
          file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    # Les threads PyTCP du tunnel userspace peuvent bloquer le join a la sortie
    # de l'interpreteur. On force une sortie nette une fois uvicorn arrete.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def _cmd_capture(args: argparse.Namespace) -> int:
    async def _run() -> None:
        from pymobiledevice3.services.pcapd import PcapdService

        tunnel = UserspaceTunnel(args.udid)
        rsd = await tunnel.open(timeout_s=30)
        svc = PcapdService(rsd)
        with open(args.out, "wb") as fh:
            await svc.write_to_pcap(
                fh,
                svc.watch(
                    packets_count=args.count,
                    process=args.process,
                    interface_name=args.iface,
                ),
            )

    print(
        f"Capture de {args.count} paquets vers {args.out} (Ctrl-C pour stopper)...",
        file=sys.stderr,
    )
    code = 0
    try:
        asyncio.run(_run())
        print(f"OK: paquets ecrits dans {args.out}", file=sys.stderr)
    except TunnelError as exc:
        print(f"erreur: {exc}", file=sys.stderr)
        code = 3
    except KeyboardInterrupt:
        print("\ninterrompu (fichier partiel ecrit).", file=sys.stderr)
        code = 130
    except StartServiceError:
        print(
            "erreur: le device a refuse de demarrer pcapd "
            "(com.apple.pcapd.shim.remote). Sur iOS 26, ce service est gate cote "
            "device et ne demarre pas via le tunnel userspace (alors que syslog, "
            "lui, marche). La vue reseau live par connexion (RxBytes/TxBytes/RTT) "
            "reste disponible via `iphone-observer serve`.",
            file=sys.stderr,
        )
        code = 4
    # Threads PyTCP du tunnel: sortie nette.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
