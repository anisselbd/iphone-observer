"""Source networking: connexions reseau live (RxBytes/TxBytes/RTT par connexion).

Channel instruments `com.apple.instruments.server.services.networking`. Service
stateful: on agrege les 3 types d'events (interface, detection de connexion,
update) en une vue des connexions actives, et on emet un snapshot throttle.

Unites observees sur device: RTT en secondes (float), bytes cumules par
connexion. Le pid peut valoir -2 (connexions systeme/tunnel). Le nom de process
est resolu cote dashboard via le dernier tick sysmontap (pid -> name).
"""
from __future__ import annotations

import time
from typing import Any, Optional

from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.network_monitor import (
    ConnectionDetectionEvent,
    ConnectionUpdateEvent,
    InterfaceDetectionEvent,
    NetworkMonitor,
)

from ..events import SOURCE_NETWORKING, EventBus


def _fmt_addr(sa) -> tuple[Optional[str], Optional[int]]:
    try:
        return str(sa.data.address), int(sa.port)
    except Exception:  # noqa: BLE001
        return None, None


def _snapshot(conns: dict, interfaces: dict, dt: float, prune_s: float) -> dict[str, Any]:
    now = time.monotonic()
    rows = []
    agg_rx = agg_tx = 0.0
    for serial in list(conns):
        c = conns[serial]
        if now - c["last_update"] > prune_s:
            del conns[serial]
            continue
        d_rx = max(0, c["rx_bytes"] - c.get("_prev_rx", 0))
        d_tx = max(0, c["tx_bytes"] - c.get("_prev_tx", 0))
        rx_rate = d_rx / dt if dt > 0 else 0.0
        tx_rate = d_tx / dt if dt > 0 else 0.0
        c["_prev_rx"] = c["rx_bytes"]
        c["_prev_tx"] = c["tx_bytes"]
        agg_rx += rx_rate
        agg_tx += tx_rate
        rows.append({
            "serial": serial,
            "pid": c["pid"],
            "iface": interfaces.get(c["iface_index"], str(c["iface_index"])),
            "remote_addr": c["remote_addr"],
            "remote_port": c["remote_port"],
            "rx_bytes": c["rx_bytes"],
            "tx_bytes": c["tx_bytes"],
            "rx_rate": round(rx_rate),
            "tx_rate": round(tx_rate),
            "rtt_ms": c["rtt_ms"],
            "age_s": round(now - c["last_update"], 1),
        })
    rows.sort(key=lambda r: r["rx_rate"] + r["tx_rate"], reverse=True)
    return {
        "interfaces": list(interfaces.values()),
        "connections": rows[:60],
        "totals": {
            "count": len(rows),
            "rx_rate": round(agg_rx),
            "tx_rate": round(agg_tx),
        },
    }


async def run(rsd, bus: EventBus, emit_interval_s: float = 2.0, prune_s: float = 30.0) -> None:
    """Agrege les events networking et emet un snapshot throttle. Leve si le
    channel tombe (le collector reconnecte)."""
    interfaces: dict[int, str] = {}
    conns: dict[int, dict[str, Any]] = {}
    last_emit = time.monotonic()

    async with DvtProvider(rsd) as dvt, NetworkMonitor(dvt) as mon:
        async for ev in mon:
            if ev is None:
                continue
            if isinstance(ev, InterfaceDetectionEvent):
                interfaces[ev.interface_index] = ev.name
            elif isinstance(ev, ConnectionDetectionEvent):
                raddr, rport = _fmt_addr(ev.remote_address)
                conns[ev.serial_number] = {
                    "pid": ev.pid,
                    "iface_index": ev.interface_index,
                    "remote_addr": raddr,
                    "remote_port": rport,
                    "rx_bytes": 0,
                    "tx_bytes": 0,
                    "rtt_ms": None,
                    "last_update": time.monotonic(),
                }
            elif isinstance(ev, ConnectionUpdateEvent):
                c = conns.get(ev.connection_serial)
                if c is not None:
                    c["rx_bytes"] = ev.rx_bytes
                    c["tx_bytes"] = ev.tx_bytes
                    # RTT expose en secondes -> millisecondes.
                    c["rtt_ms"] = round(ev.avg_rtt * 1000, 1) if ev.avg_rtt else None
                    c["last_update"] = time.monotonic()

            now = time.monotonic()
            if now - last_emit >= emit_interval_s:
                snap = _snapshot(conns, interfaces, now - last_emit, prune_s)
                last_emit = now
                bus.emit(SOURCE_NETWORKING, "connections", snap)
