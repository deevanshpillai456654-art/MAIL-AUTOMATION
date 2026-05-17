"""
ConnectorWorker — asyncio-based background worker.

Polls queue_jobs for pending connector sync/webhook tasks and dispatches them.
One global worker loop runs inside the FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional

log = logging.getLogger(__name__)

_POLL_INTERVAL = 5.0      # seconds between queue polls
_MAX_CONCURRENT = 10      # max simultaneous connector tasks


def _utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ConnectorWorker:
    """
    Background worker that:
      1. Polls queue_jobs for 'queued' connector jobs
      2. Dispatches to the right ConnectorBase subclass
      3. Handles retries, marks complete/failed
      4. Runs scheduled syncs based on connector config
    """

    def __init__(self, db, registry) -> None:
        self._db = db
        self._registry = registry
        self._running = False
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        self._task: Optional[asyncio.Task] = None
        self._active: int = 0
        self._processed: int = 0

    def is_running(self) -> bool:
        return self._running

    def active_count(self) -> int:
        return self._active

    def processed_count(self) -> int:
        return self._processed

    def start(self) -> None:
        if not self._running:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                log.warning("ConnectorWorker start skipped: no running asyncio loop")
                return
            self._running = True
            self._task = loop.create_task(self._loop(), name="connector-worker")
            log.info("ConnectorWorker started")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
        log.info("ConnectorWorker stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._process_pending_jobs()
                await self._trigger_due_syncs()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("ConnectorWorker loop error: %s", exc, exc_info=True)
            await asyncio.sleep(_POLL_INTERVAL)

    async def _process_pending_jobs(self) -> None:
        jobs = self._db.fetch_all(
            """SELECT * FROM queue_jobs
               WHERE status='queued'
               ORDER BY created_at ASC
               LIMIT 20"""
        )
        tasks = []
        for job in jobs:
            # Claim the job
            updated = self._db.execute(
                "UPDATE queue_jobs SET status='processing', updated_at=? WHERE id=? AND status='queued'",
                (_utc(), job["id"]),
            ).rowcount
            if updated:
                tasks.append(asyncio.create_task(self._run_job(dict(job))))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_job(self, job: Dict) -> None:
        self._active += 1
        async with self._semaphore:
            job_id = job["id"]
            job_type = job.get("job_type", "")
            connector_id_installed = job.get("connector_id", "")
            tenant_id = job.get("tenant_id", "")
            payload = json.loads(job.get("payload_json") or "{}")

            try:
                # Load the installed connector record
                row = self._db.fetch_one(
                    "SELECT * FROM connectors WHERE id=?", (connector_id_installed,)
                )
                if not row:
                    raise ValueError(f"Connector instance {connector_id_installed} not found")

                # Resolve connector class: manifest_id > name match > payload hint
                cls = self._registry.get_class(row.get("manifest_id", ""))
                if not cls:
                    cls = self._registry._find_class_by_instance(connector_id_installed)
                if not cls:
                    cid = payload.get("connector_id", "")
                    cls = self._registry.get_class(cid)
                if not cls:
                    raise ValueError(f"No connector class for {connector_id_installed}")

                from ...shared.utils import decrypt_config
                config = decrypt_config(row.get("config_json") or "")
                connector = cls(
                    instance_id=connector_id_installed,
                    tenant_id=tenant_id,
                    config=config,
                    db=self._db,
                )

                if job_type == "sync":
                    entity = payload.get("entity", "all")
                    if entity == "all":
                        await connector.run_sync_all()
                    else:
                        await connector.sync(entity)
                elif job_type == "webhook":
                    event_type = payload.get("event_type", "")
                    raw_body = payload.get("raw_body", "").encode()
                    headers = payload.get("headers", {})
                    wh_payload = payload.get("payload", {})
                    await connector.handle_webhook(event_type, wh_payload, raw_body, headers)
                elif job_type == "health_check":
                    result = await connector.health_check()
                    healthy = result.get("healthy", False)
                    connector._record_health(healthy, result.get("latency_ms"),
                                            result.get("message", ""))
                else:
                    log.warning("Unknown job type: %s", job_type)

                await connector.close()
                self._db.execute(
                    "UPDATE queue_jobs SET status='completed', updated_at=? WHERE id=?",
                    (_utc(), job_id),
                )
                self._processed += 1

            except Exception as exc:
                log.error("Job %s failed: %s", job_id, exc)
                attempts = job.get("attempts", 0) + 1
                max_attempts = job.get("max_attempts", 3)
                new_status = "dead" if attempts >= max_attempts else "failed"
                self._db.execute(
                    """UPDATE queue_jobs
                       SET status=?, attempts=?, error=?, updated_at=?
                       WHERE id=?""",
                    (new_status, attempts, str(exc)[:500], _utc(), job_id),
                )
            finally:
                self._active = max(0, self._active - 1)

    async def _trigger_due_syncs(self) -> None:
        """
        Enqueue sync jobs for active connectors whose last_sync is stale.
        Default sync interval: 1 hour.
        """
        rows = self._db.fetch_all(
            """SELECT c.id, c.tenant_id, c.config_json, c.last_sync
               FROM connectors c
               WHERE c.status='active' AND c.is_active=1
               AND (c.last_sync IS NULL
                    OR (strftime('%s','now') - strftime('%s', c.last_sync)) > 3600)
               LIMIT 10"""
        )
        for row in rows:
            # Check if there's already a queued sync job
            existing = self._db.fetch_one(
                "SELECT id FROM queue_jobs WHERE connector_id=? AND job_type='sync' AND status IN ('queued','processing')",
                (row["id"],),
            )
            if not existing:
                job_id = f"job_{__import__('uuid').uuid4().hex}"
                now = _utc()
                self._db.execute(
                    """INSERT INTO queue_jobs
                       (id, connector_id, tenant_id, job_type, status,
                        payload_json, attempts, max_attempts, created_at, updated_at)
                       VALUES (?,?,?,'sync','queued','{"entity":"all"}',0,3,?,?)""",
                    (job_id, row["id"], row["tenant_id"], now, now),
                )
                # Update last_sync to prevent duplicate scheduling
                self._db.execute(
                    "UPDATE connectors SET last_sync=? WHERE id=?",
                    (now, row["id"]),
                )


# Global worker instance
_worker: Optional[ConnectorWorker] = None


def get_worker() -> Optional[ConnectorWorker]:
    return _worker


def init_worker(db, registry) -> ConnectorWorker:
    global _worker
    _worker = ConnectorWorker(db, registry)
    return _worker
