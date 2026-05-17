"""
QueueAdapter — plugin-safe job queue access.

Wraps the platform queue so plugins can enqueue/dequeue jobs without
importing the core queue system directly.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class QueueAdapter:
    """
    Provides enqueue / dequeue / complete / fail operations for plugin jobs.

    Backed by the platform queue_jobs table (same schema as connector jobs).
    """

    def __init__(
        self,
        raw_db: Any,
        plugin_id: str,
        tenant_id: str,
    ) -> None:
        self._db        = raw_db
        self._plugin_id = plugin_id
        self._tenant_id = tenant_id

    def _utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def enqueue(
        self,
        job_type: str,
        payload: Dict[str, Any],
        *,
        max_attempts: int = 3,
        delay_seconds: int = 0,
        priority: int = 2,
    ) -> str:
        job_id = f"job_{uuid.uuid4().hex}"
        now = self._utc()
        self._db.execute(
            """INSERT INTO queue_jobs
               (id, connector_id, tenant_id, job_type, status,
                payload_json, attempts, max_attempts, created_at, updated_at)
               VALUES (?,?,?,?,'queued',?,0,?,?,?)""",
            (job_id, self._plugin_id, self._tenant_id, job_type,
             json.dumps(payload), max_attempts, now, now),
        )
        return job_id

    def complete(self, job_id: str) -> None:
        self._db.execute(
            "UPDATE queue_jobs SET status='completed', updated_at=? WHERE id=?",
            (self._utc(), job_id),
        )

    def fail(self, job_id: str, error: str) -> None:
        self._db.execute(
            """UPDATE queue_jobs
               SET status=CASE WHEN attempts+1>=max_attempts THEN 'dead_letter' ELSE 'failed' END,
                   attempts=attempts+1, error=?, updated_at=?
               WHERE id=?""",
            (error[:500], self._utc(), job_id),
        )

    def fetch_pending(self, limit: int = 10) -> list:
        return self._db.fetch_all(
            """SELECT * FROM queue_jobs
               WHERE connector_id=? AND tenant_id=? AND status='queued'
               ORDER BY created_at ASC LIMIT ?""",
            (self._plugin_id, self._tenant_id, limit),
        ) or []
