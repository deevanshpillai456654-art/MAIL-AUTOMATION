"""SQLite-backed persistent job queue for local-first recovery-safe tasks."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional


class PersistentJobQueue:
    """Small durable queue with lease/retry semantics and crash recovery."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS persistent_jobs (
                    job_id TEXT PRIMARY KEY,
                    queue TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    lease_until REAL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_persistent_jobs_status ON persistent_jobs(queue, status, created_at)")

    def enqueue(self, queue: str, payload: Dict[str, Any], *, job_id: Optional[str] = None, max_attempts: int = 5) -> str:
        job_id = job_id or f"job_{uuid.uuid4().hex}"
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO persistent_jobs
                (job_id, queue, payload, status, attempts, max_attempts, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)
                """,
                (job_id, queue, json.dumps(payload, sort_keys=True), max(1, int(max_attempts)), now, now),
            )
        return job_id

    def lease_next(self, queue: str, *, lease_seconds: int = 60) -> Optional[Dict[str, Any]]:
        now = time.time()
        lease_until = now + max(1, int(lease_seconds))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM persistent_jobs
                WHERE queue = ? AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (queue,),
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            conn.execute(
                """
                UPDATE persistent_jobs
                SET status = 'leased', attempts = attempts + 1, lease_until = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (lease_until, now, row["job_id"]),
            )
            conn.execute("COMMIT")
            data = dict(row)
            data["payload"] = json.loads(data["payload"])
            data["status"] = "leased"
            data["attempts"] = int(data["attempts"]) + 1
            data["lease_until"] = lease_until
            return data

    def complete(self, job_id: str) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE persistent_jobs SET status = 'completed', lease_until = NULL, updated_at = ? WHERE job_id = ?",
                (now, job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT attempts, max_attempts FROM persistent_jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return
            status = "failed" if int(row["attempts"] or 0) >= int(row["max_attempts"] or 1) else "pending"
            conn.execute(
                """
                UPDATE persistent_jobs
                SET status = ?, lease_until = NULL, last_error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, str(error)[:1000], now, job_id),
            )

    def recover_stale_leases(self) -> int:
        now = time.time()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE persistent_jobs
                SET status = 'pending', lease_until = NULL, updated_at = ?
                WHERE status = 'leased' AND lease_until IS NOT NULL AND lease_until < ?
                """,
                (now, now),
            )
            return cur.rowcount

    def counts(self) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM persistent_jobs GROUP BY status").fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}


__all__ = ["PersistentJobQueue"]
