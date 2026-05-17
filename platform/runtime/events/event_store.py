"""
EventStore — durable, tenant-aware event persistence for the plugin runtime.

Writes to SQLite by default; swappable for any other backend by subclassing.
Supports efficient replay queries by event_type, tenant, source, and time range.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

log = logging.getLogger(__name__)

_DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "runtime_events.db"


class EventStore:
    """
    SQLite-backed event store for the RuntimeEventBus.

    All writes are non-blocking (WAL mode).  Reads support cursor-based
    pagination for large result sets.
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._path = Path(db_path or _DEFAULT_DB)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    # ── Schema ─────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS runtime_events (
                    event_id        TEXT PRIMARY KEY,
                    event_type      TEXT NOT NULL,
                    source          TEXT NOT NULL,
                    tenant_id       TEXT NOT NULL,
                    payload_json    TEXT NOT NULL DEFAULT '{}',
                    priority        INTEGER NOT NULL DEFAULT 2,
                    published_at    TEXT NOT NULL,
                    trace_id        TEXT,
                    correlation_id  TEXT,
                    replay          INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_re_tenant   ON runtime_events(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_re_type     ON runtime_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_re_source   ON runtime_events(source);
                CREATE INDEX IF NOT EXISTS idx_re_published ON runtime_events(published_at);
                CREATE INDEX IF NOT EXISTS idx_re_trace    ON runtime_events(trace_id);

                CREATE TABLE IF NOT EXISTS event_subscriptions_log (
                    id              TEXT PRIMARY KEY,
                    event_id        TEXT NOT NULL,
                    sub_id          TEXT NOT NULL,
                    delivered_at    TEXT NOT NULL,
                    success         INTEGER NOT NULL DEFAULT 1,
                    error_msg       TEXT
                );
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self._path), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Write ──────────────────────────────────────────────────────────────

    async def append(self, event: Any) -> None:
        """Persist a RuntimeEvent (non-blocking via thread lock)."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO runtime_events
                       (event_id, event_type, source, tenant_id, payload_json,
                        priority, published_at, trace_id, correlation_id, replay)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event.event_id,
                        event.event_type,
                        event.source,
                        event.tenant_id,
                        json.dumps(event.payload),
                        int(event.priority),
                        event.published_at,
                        event.trace_id,
                        event.correlation_id,
                        1 if event.replay else 0,
                    ),
                )

    def log_delivery(
        self,
        event_id: str,
        sub_id: str,
        *,
        success: bool = True,
        error_msg: Optional[str] = None,
    ) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO event_subscriptions_log
                       (id, event_id, sub_id, delivered_at, success, error_msg)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        f"del_{uuid.uuid4().hex[:12]}",
                        event_id,
                        sub_id,
                        datetime.now(timezone.utc).isoformat(),
                        1 if success else 0,
                        error_msg,
                    ),
                )

    # ── Read ───────────────────────────────────────────────────────────────

    def query(
        self,
        *,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        trace_id: Optional[str] = None,
        replay_only: bool = False,
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Flexible query with optional filters; returns raw dicts."""
        conditions: List[str] = []
        params: List[Any] = []

        if tenant_id:
            conditions.append("tenant_id = ?");  params.append(tenant_id)
        if event_type:
            if "%" in event_type or "*" in event_type:
                conditions.append("event_type LIKE ?")
                params.append(event_type.replace("*", "%"))
            else:
                conditions.append("event_type = ?"); params.append(event_type)
        if source:
            conditions.append("source = ?"); params.append(source)
        if since:
            conditions.append("published_at >= ?"); params.append(since)
        if until:
            conditions.append("published_at <= ?"); params.append(until)
        if trace_id:
            conditions.append("trace_id = ?"); params.append(trace_id)
        if replay_only:
            conditions.append("replay = 1")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM runtime_events {where} ORDER BY published_at ASC LIMIT ? OFFSET ?"  # nosec B608
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            d["payload"] = json.loads(d.pop("payload_json", "{}"))
            result.append(d)
        return result

    def count(
        self,
        *,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        since: Optional[str] = None,
    ) -> int:
        conditions: List[str] = []
        params: List[Any] = []
        if tenant_id:
            conditions.append("tenant_id = ?"); params.append(tenant_id)
        if event_type:
            conditions.append("event_type = ?"); params.append(event_type)
        if since:
            conditions.append("published_at >= ?"); params.append(since)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) as n FROM runtime_events {where}", params).fetchone()  # nosec B608
        return row["n"] if row else 0

    def get_by_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        return self.query(trace_id=trace_id, limit=1000)

    def purge_before(self, cutoff_iso: str) -> int:
        """Delete events older than *cutoff_iso* (ISO8601). Returns deleted count."""
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM runtime_events WHERE published_at < ?", (cutoff_iso,)
                )
                return cur.rowcount
