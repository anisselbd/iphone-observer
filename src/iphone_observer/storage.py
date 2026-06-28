"""Storage SQLite local (decide avec l'utilisateur): persiste les events et sert
la timeline unifiee.

Schema fidele a l'enveloppe: une table events(seq, ts, source, type, udid, data)
ou data est le JSON du payload. Index sur ts et (source, type, ts) pour des
requetes timeline rapides. WAL pour l'ecriture concurrente.

Maitrise du volume: deux flux ont un gros payload (sysmontap = ~600 process/s,
networking = jusqu'a 60 connexions). En storage on n'en garde que les totaux +
le top N (par defaut 20). Le flux WebSocket live, lui, reste complet. C'est un
choix assume pour borner la croissance de la base; documente, pas cache.

Acces concurrent: connexion sqlite partagee (check_same_thread=False), toutes
les operations passent par to_thread serialise par un verrou asyncio.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from .events import EventBus

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq    INTEGER PRIMARY KEY,
    ts     REAL    NOT NULL,
    source TEXT    NOT NULL,
    type   TEXT    NOT NULL,
    udid   TEXT,
    data   TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_src_ts ON events(source, type, ts);
"""


def _compact(source: str, type: str, data: dict[str, Any], top_n: int) -> dict[str, Any]:
    """Reduit les payloads volumineux pour le storage (top N + totaux)."""
    if source == "sysmontap" and type == "process_tick":
        procs = sorted(data.get("processes", []), key=lambda p: p.get("cpu", 0), reverse=True)
        return {
            "interval_ms": data.get("interval_ms"),
            "totals": data.get("totals"),
            "processes": procs[:top_n],
        }
    if source == "networking" and type == "connections":
        return {
            "interfaces": data.get("interfaces"),
            "totals": data.get("totals"),
            "connections": data.get("connections", [])[:top_n],
        }
    return data


class Storage:
    def __init__(
        self,
        db_path: str,
        flush_interval_s: float = 2.0,
        top_n: int = 20,
    ) -> None:
        self.db_path = db_path
        self.flush_interval_s = flush_interval_s
        self.top_n = top_n
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    async def open(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        self._conn = conn

    async def close(self) -> None:
        if self._conn is not None:
            conn = self._conn
            self._conn = None
            async with self._lock:
                await asyncio.to_thread(conn.close)

    # --- ecriture ------------------------------------------------------------

    async def run(self, bus: EventBus) -> None:
        """Tache longue: persiste tout event du bus, par lots."""
        queue = bus.subscribe()
        buf: list[tuple] = []
        last_flush = time.monotonic()
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=self.flush_interval_s)
                    data = _compact(payload["source"], payload["type"], payload["data"], self.top_n)
                    buf.append((
                        payload["seq"], payload["ts"], payload["source"],
                        payload["type"], payload.get("udid", ""),
                        json.dumps(data, ensure_ascii=False, default=str),
                    ))
                except asyncio.TimeoutError:
                    pass
                now = time.monotonic()
                if buf and (now - last_flush >= self.flush_interval_s or len(buf) >= 1000):
                    await self._flush(buf)
                    buf = []
                    last_flush = now
        except asyncio.CancelledError:
            if buf:
                await self._flush(buf)
            raise
        finally:
            bus.unsubscribe(queue)

    async def _flush(self, rows: list[tuple]) -> None:
        if self._conn is None:
            return
        conn = self._conn

        def _do() -> None:
            conn.executemany(
                "INSERT OR REPLACE INTO events(seq, ts, source, type, udid, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()

        async with self._lock:
            await asyncio.to_thread(_do)

    # --- lecture (timeline) --------------------------------------------------

    async def timeline(self, minutes: float = 10.0, max_points: int = 600) -> dict[str, Any]:
        """Series temporelles superposables sur un meme axe temps."""
        if self._conn is None:
            return {"available": False}
        until = time.time()
        since = until - minutes * 60
        conn = self._conn

        def _series(source: str, type: str, expr: str) -> list[list[float]]:
            cur = conn.execute(
                "SELECT ts, json_extract(data, ?) FROM events "
                "WHERE source=? AND type=? AND ts>=? ORDER BY ts",
                (expr, source, type, since),
            )
            rows = [[r[0], r[1]] for r in cur.fetchall() if r[1] is not None]
            return _decimate(rows, max_points)

        def _do() -> dict[str, Any]:
            cpu = _series("sysmontap", "process_tick", "$.totals.aggregate_cpu")
            top = _series("sysmontap", "process_tick", "$.totals.top_cpu")
            temp = _series("diagnostics", "battery", "$.temperature_c")
            level = _series("diagnostics", "battery", "$.level_pct")
            net = _series("networking", "connections", "$.totals.rx_rate")
            net_tx = _series("networking", "connections", "$.totals.tx_rate")

            # Indexation: transitions d'etat
            cur = conn.execute(
                "SELECT ts, json_extract(data,'$.state') FROM events "
                "WHERE source='analyzer' AND type='indexing' AND ts>=? ORDER BY ts",
                (since,),
            )
            idx_raw = cur.fetchall()
            indexing = []
            prev = None
            for ts, st in idx_raw:
                if st != prev:
                    indexing.append([ts, st])
                    prev = st

            # Erreurs syslog comme marqueurs
            cur = conn.execute(
                "SELECT ts, json_extract(data,'$.process'), json_extract(data,'$.message') "
                "FROM events WHERE source='syslog' AND type='line' "
                "AND json_extract(data,'$.level') IN ('Error','Fault') AND ts>=? "
                "ORDER BY ts DESC LIMIT 60",
                (since,),
            )
            errors = [[r[0], f"{r[1]}: {r[2]}"] for r in cur.fetchall()][::-1]

            cur = conn.execute("SELECT COUNT(*) FROM events")
            total_rows = cur.fetchone()[0]

            return {
                "available": True,
                "since": since,
                "until": until,
                "minutes": minutes,
                "total_rows": total_rows,
                "series": {
                    "cpu_aggregate": cpu,
                    "cpu_top": top,
                    "battery_temp_c": temp,
                    "battery_level": level,
                    "net_rx_rate": net,
                    "net_tx_rate": net_tx,
                },
                "indexing": indexing,
                "errors": errors,
            }

        async with self._lock:
            return await asyncio.to_thread(_do)


def _decimate(rows: list[list[float]], max_points: int) -> list[list[float]]:
    """Reduit une serie a max_points par striding regulier."""
    n = len(rows)
    if n <= max_points:
        return rows
    step = n / max_points
    return [rows[int(i * step)] for i in range(max_points)]
