"""
DeadLetterQueue — captures events whose handlers failed or timed out.

Failed events are stored persistently and can be:
  - Inspected via DLQ admin endpoints
  - Re-queued for retry after the handler bug is fixed
  - Discarded after manual review
"""
from __future__ import annotations

import asyncio
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


class DeadLetterQueue:
    """
    Persistent dead-letter queue backed by SQLite.

    Items are inserted by the RuntimeEventBus on handler failure.
    DLQ is isolated from the live event flow — the main bus continues
    operating regardless of DLQ write failures.
    """

    def __init__(self, db_path: Optional[str | Path] = None) -> None:
        self._path = Path(db_path or _DEFAULT_DB)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

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

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS dead_letter_events (
                    dlq_id          TEXT PRIMARY KEY,
                    event_id        TEXT NOT NULL,
                    event_type      TEXT NOT NULL,
                    source          TEXT NOT NULL,
                    tenant_id       TEXT NOT NULL,
                    payload_json    TEXT NOT NULL DEFAULT '{}',
                    failed_sub_id   TEXT NOT NULL,
                    failure_reason  TEXT NOT NULL,
                    failed_at       TEXT NOT NULL,
                    retry_count     INTEGER NOT NULL DEFAULT 0,
                    resolved        INTEGER NOT NULL DEFAULT 0,
                    resolved_at     TEXT,
                    resolution_note TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_dlq_tenant ON dead_letter_events(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_dlq_type   ON dead_letter_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_dlq_status ON dead_letter_events(resolved);
            """)

    # ── Write ──────────────────────────────────────────────────────────────

    async def enqueue(self, event: Any, sub_id: str, reason: str) -> str:
        dlq_id = f"dlq_{uuid.uuid4().hex}"
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO dead_letter_events
                       (dlq_id, event_id, event_type, source, tenant_id,
                        payload_json, failed_sub_id, failure_reason, failed_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        dlq_id,
                        event.event_id,
                        event.event_type,
                        event.source,
                        event.tenant_id,
                        json.dumps(event.payload),
                        sub_id,
                        reason[:500],
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        log.warning(
            "DLQ: event %s → sub %s failed: %s (dlq_id=%s)",
            event.event_id, sub_id, reason[:100], dlq_id,
        )
        return dlq_id

    # ── Query ─────────────────────────────────────────────────────────────

    def list_pending(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        conditions = ["resolved = 0"]
        params: List[Any] = []
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        where = "WHERE " + " AND ".join(conditions)
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM dead_letter_events {where} ORDER BY failed_at DESC LIMIT ? OFFSET ?",  # nosec B608
                params,
            ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            d["payload"] = json.loads(d.pop("payload_json", "{}"))
            result.append(d)
        return result

    def count_pending(self, tenant_id: Optional[str] = None) -> int:
        params: List[Any] = [0]
        where = "WHERE resolved = ?"
        if tenant_id:
            where += " AND tenant_id = ?"
            params.append(tenant_id)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) as n FROM dead_letter_events {where}", params  # nosec B608
            ).fetchone()
        return row["n"] if row else 0

    # ── Operations ────────────────────────────────────────────────────────

    async def retry(self, dlq_id: str, bus: Any) -> bool:
        """Re-publish a DLQ event and increment its retry_count."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dead_letter_events WHERE dlq_id = ?", (dlq_id,)
            ).fetchone()
        if not row:
            return False

        from .event_bus import RuntimeEvent, EventPriority  # local import
        evt = RuntimeEvent(
            event_type=row["event_type"],
            source=row["source"],
            tenant_id=row["tenant_id"],
            payload=json.loads(row["payload_json"]),
        )
        await bus.publish_event(evt)

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE dead_letter_events SET retry_count = retry_count + 1 WHERE dlq_id = ?",
                    (dlq_id,),
                )
        return True

    def resolve(self, dlq_id: str, note: str = "") -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """UPDATE dead_letter_events
                       SET resolved=1, resolved_at=?, resolution_note=?
                       WHERE dlq_id=?""",
                    (datetime.now(timezone.utc).isoformat(), note, dlq_id),
                )
        return cur.rowcount > 0

    def discard_all_resolved(self) -> int:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("DELETE FROM dead_letter_events WHERE resolved = 1")
        return cur.rowcount
