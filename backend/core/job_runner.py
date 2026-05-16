"""Async job runner backed by PersistentJobQueue.

Phase-1 design: runs up to `concurrency` background tasks concurrently using
asyncio.  Sync handlers are dispatched into a ThreadPoolExecutor so they cannot
stall the event loop.  Supports both sync and async handler functions.

Usage
-----
    runner = init_job_runner(queue, concurrency=4)
    runner.register("telemetry_upload", upload_telemetry)
    runner.register("sync_retry", retry_sync)

    # In lifespan:
    await runner.start()
    ...
    await runner.stop()

    # Enqueue from anywhere:
    runner.enqueue("telemetry_upload", {"account_id": 42})
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional

from backend.core.persistent_job_queue import PersistentJobQueue

logger = logging.getLogger("job_runner")

# Exponential backoff delay per attempt number (seconds)
_BACKOFF_SECONDS = [5, 15, 60, 300, 900]


def _backoff(attempt: int) -> float:
    idx = min(attempt - 1, len(_BACKOFF_SECONDS) - 1)
    return float(_BACKOFF_SECONDS[idx])


class JobRunner:
    """
    Lightweight async job runner over a PersistentJobQueue.

    Spawns up to `concurrency` concurrent asyncio tasks.  Each task is either
    awaited directly (async handlers) or run in a ThreadPoolExecutor (sync
    handlers) so the event loop is never blocked.
    """

    def __init__(
        self,
        queue: PersistentJobQueue,
        *,
        concurrency: int = 4,
        poll_interval: float = 2.0,
        lease_seconds: int = 120,
    ) -> None:
        self._queue = queue
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._lease_seconds = lease_seconds
        self._handlers: Dict[str, Callable] = {}
        self._pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="job_runner")
        self._sem: Optional[asyncio.Semaphore] = None
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None

    # ── registration ──────────────────────────────────────────────────────────

    def register(self, queue_name: str, handler: Callable) -> None:
        """Register a sync or async callable as the handler for `queue_name`."""
        self._handlers[queue_name] = handler

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._sem = asyncio.Semaphore(self._concurrency)

        # Recover stale leases from any previous crash
        loop = asyncio.get_event_loop()
        recovered = await loop.run_in_executor(None, self._queue.recover_stale_leases)
        if recovered:
            logger.info("Recovered %d stale job leases on startup", recovered)

        self._loop_task = asyncio.create_task(self._poll_loop(), name="job_runner_poll")
        logger.info(
            "JobRunner started (concurrency=%d, poll_interval=%.1fs, queues=%s)",
            self._concurrency,
            self._poll_interval,
            list(self._handlers),
        )

    async def stop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._pool.shutdown(wait=False)
        logger.info("JobRunner stopped")

    # ── enqueue helper ────────────────────────────────────────────────────────

    def enqueue(self, queue_name: str, payload: Dict[str, Any], *, max_attempts: int = 5, job_id: Optional[str] = None) -> str:
        """Thread-safe: enqueue a job and return its job_id."""
        return self._queue.enqueue(queue_name, payload, max_attempts=max_attempts, job_id=job_id)

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "concurrency": self._concurrency,
            "poll_interval_seconds": self._poll_interval,
            "registered_queues": list(self._handlers),
            "queue_counts": self._queue.counts(),
        }

    # ── internals ─────────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        loop = asyncio.get_event_loop()
        queues = list(self._handlers)
        while self._running:
            found_any = False
            for queue_name in queues:
                job = await loop.run_in_executor(
                    None,
                    lambda q=queue_name: self._queue.lease_next(q, lease_seconds=self._lease_seconds),
                )
                if job:
                    found_any = True
                    asyncio.create_task(self._dispatch(job, queue_name), name=f"job_{job['job_id'][:8]}")
            if not found_any:
                await asyncio.sleep(self._poll_interval)

    async def _dispatch(self, job: Dict[str, Any], queue_name: str) -> None:
        assert self._sem is not None
        job_id = job["job_id"]
        handler = self._handlers.get(queue_name)
        if not handler:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: self._queue.fail(job_id, f"No handler registered for queue '{queue_name}'")
            )
            return

        async with self._sem:
            loop = asyncio.get_event_loop()
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(job["payload"])
                else:
                    await loop.run_in_executor(self._pool, lambda: handler(job["payload"]))
                await loop.run_in_executor(None, lambda: self._queue.complete(job_id))
                logger.debug("Job %s completed (queue=%s, attempt=%d)", job_id, queue_name, job.get("attempts", 1))
            except Exception as exc:
                attempts = int(job.get("attempts", 1))
                delay = _backoff(attempts)
                logger.warning(
                    "Job %s failed (queue=%s, attempt=%d, backoff=%.0fs): %s",
                    job_id, queue_name, attempts, delay, exc,
                )
                await loop.run_in_executor(None, lambda: self._queue.fail(job_id, str(exc)))


# ── module-level singleton ────────────────────────────────────────────────────

_runner: Optional[JobRunner] = None


def get_job_runner() -> Optional[JobRunner]:
    """Return the running JobRunner, or None if not initialised."""
    return _runner


def init_job_runner(queue: PersistentJobQueue, **kwargs: Any) -> JobRunner:
    """Create and register the global JobRunner.  Call once during app startup."""
    global _runner
    _runner = JobRunner(queue, **kwargs)
    return _runner


__all__ = ["JobRunner", "get_job_runner", "init_job_runner"]
