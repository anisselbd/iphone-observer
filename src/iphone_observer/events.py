"""Schema d'events horodate unique + bus de diffusion.

Enveloppe unique pour TOUS les flux (sysmontap, diagnostics, syslog, networking,
pcap, collector). Un nouveau flux = un nouveau couple (source, type), sans
toucher au transport ni au storage.

    {
      "ts": 1782605077.31,     # epoch float, horloge host
      "source": "sysmontap",   # qui produit l'event
      "udid": "00008150-...",
      "type": "process_tick",  # discriminant dans la source
      "seq": 12843,            # compteur monotone global (ordre)
      "data": { ... }          # payload specifique a (source, type)
    }

Decisions actees avec l'utilisateur: enveloppe unique + payload par source;
storage SQLite (phase 6) sur une table events(ts, source, type, udid, seq, data).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

# Sources connues (string libre, mais on centralise les noms ici).
SOURCE_COLLECTOR = "collector"
SOURCE_SYSMONTAP = "sysmontap"
SOURCE_DIAGNOSTICS = "diagnostics"
SOURCE_SYSLOG = "syslog"
SOURCE_NETWORKING = "networking"
SOURCE_PCAP = "pcap"
SOURCE_ANALYZER = "analyzer"
SOURCE_GRAPHICS = "graphics"


@dataclass(slots=True)
class Event:
    source: str
    type: str
    data: dict[str, Any]
    udid: str = ""
    ts: float = 0.0
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "source": self.source,
            "udid": self.udid,
            "type": self.type,
            "seq": self.seq,
            "data": self.data,
        }


class EventBus:
    """Pub/sub asyncio. Horodate et numerote les events, garde le dernier par
    (source, type) pour l'etat initial des nouveaux abonnes, et diffuse avec
    backpressure (on jette le plus ancien si un abonne est en retard)."""

    def __init__(self, udid: str = "", queue_maxsize: int = 8) -> None:
        self.udid = udid
        self._queue_maxsize = queue_maxsize
        self._seq = 0
        self._subscribers: set[asyncio.Queue] = set()
        self._latest: dict[tuple[str, str], dict] = {}

    def publish(self, event: Event) -> dict:
        """Finalise (ts, seq, udid) puis diffuse. Renvoie le dict envoye."""
        self._seq += 1
        event.seq = self._seq
        if event.ts == 0.0:
            event.ts = time.time()
        if not event.udid:
            event.udid = self.udid
        payload = event.to_dict()
        self._latest[(event.source, event.type)] = payload
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)
        return payload

    def emit(self, source: str, type: str, data: dict[str, Any]) -> dict:
        """Raccourci: construit l'Event et le publie."""
        return self.publish(Event(source=source, type=type, data=data))

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def snapshot(self) -> list[dict]:
        """Dernier event connu par (source, type), pour amorcer un client."""
        return list(self._latest.values())

    def latest(self, source: str, type: str) -> dict | None:
        """Dernier event d'un couple (source, type), ou None."""
        return self._latest.get((source, type))
