"""Source syslog: stream des logs systeme, filtre et rate-limite.

Service `com.apple.syslog_relay`. iOS debite ~600 lignes/s, donc on ne diffuse
PAS tout: par defaut on garde les daemons d'indexation (utiles a la phase 4) et
toute ligne de niveau Error/Fault, avec une limite d'1 ligne/s/process pour
rester lisible. Les erreurs ne sont pas throttlees.

Format d'une ligne syslog_relay:
    Jun 28 02:51:27 iPhone-de-Lbd proc(subsystem)[pid] <Level>: message
"""
from __future__ import annotations

import re
import time
from typing import Any, Iterable, Optional

from pymobiledevice3.services.syslog import SyslogService

from ..events import SOURCE_SYSLOG, EventBus

# Daemons d'indexation / analyse on-device (coeur de la phase 4).
INDEXING_DAEMONS = (
    "photoanalysisd",
    "mediaanalysisd",
    "corespotlightd",
    "cloudd",
    "photolibraryd",
    "spotlightknowledged",
    "spotlightknowledged.updater",
)

_LINE_RE = re.compile(
    r"^\w{3}\s+\d+\s+(?P<time>[\d:]+)\s+\S+\s+(?P<proc>[^\[]+)\[(?P<pid>\d+)\]"
    r"\s*(?:<(?P<level>\w+)>)?:?\s*(?P<msg>.*)$"
)

_ALERT_LEVELS = {"Error", "Fault"}


def parse_line(line: str) -> Optional[dict[str, Any]]:
    m = _LINE_RE.match(line)
    if not m:
        return None
    proc_full = m.group("proc").strip()
    name, subsystem = proc_full, None
    if proc_full.endswith(")") and "(" in proc_full:
        name, _, sub = proc_full.partition("(")
        name = name.strip()
        subsystem = sub.rstrip(")")
    return {
        "time": m.group("time"),
        "process": name,
        "subsystem": subsystem,
        "pid": int(m.group("pid")),
        "level": m.group("level") or "",
        "message": m.group("msg"),
    }


async def run(
    rsd,
    bus: EventBus,
    watch: Optional[Iterable[str]] = None,
    min_interval_s: float = 1.0,
) -> None:
    """Stream filtre. Leve si le relay tombe (le collector reconnecte)."""
    watchset = set(watch) if watch is not None else set(INDEXING_DAEMONS)
    last_emit: dict[str, float] = {}
    svc = SyslogService(rsd)
    async for line in svc.watch():
        parsed = parse_line(line)
        if parsed is None:
            continue
        is_alert = parsed["level"] in _ALERT_LEVELS
        # On garde: les daemons surveilles, plus toute alerte (Error/Fault) de
        # n'importe quel process.
        if not is_alert and parsed["process"] not in watchset:
            continue
        # Rate-limit par process, alertes comprises: un seul process tres bavard
        # (ex: erreurs repetees d'inference) ne doit pas noyer le panneau.
        now = time.monotonic()
        if now - last_emit.get(parsed["process"], 0.0) < min_interval_s:
            continue
        last_emit[parsed["process"]] = now
        bus.emit(SOURCE_SYSLOG, "line", parsed)
