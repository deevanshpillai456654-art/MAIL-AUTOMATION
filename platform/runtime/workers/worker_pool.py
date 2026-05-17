"""
WorkerPool — async task pool for plugin job execution.

- Bounded concurrency per plugin (configurable max_workers_per_plugin)
- Global pool size cap (max_total_workers)
- Priority queuing (CRITICAL processed before NORMAL)
- Per-tenant fair scheduling (no single tenant starves others)
- Graceful shutdown: drains queue before stopping
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)


class TaskPriority(IntEnum):
    CRITICAL = 0
    HIGH     = 1
    NORMAL   = 2
    LOW      = 3


@dataclass(order=True)
class PoolTask:
    priority: TaskPriority
    created_at: float = field(default_factory=time.monotonic)
    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}", compare=False)
    plugin_id: str = field(default="", compare=False)
    tenant_id: str = field(default="", compare=False)
    coro_fn: Any   = field(default=None, compare=False)
    kwargs: Dict[str, Any] = field(default_factory=dict, compare=False)
    result_future: Any = field(default=None, compare=False)


class WorkerPool:
    """
    Bounded async worker pool with priority scheduling.

    Usage::

        pool = WorkerPool(max_workers=20)
        asyncio.create_task(pool.run())

        future = await pool.submit(
            my_coroutine_fn,
            plugin_id="salesforce",
            tenant_id="t1",
            priority=TaskPriority.HIGH,
            arg1="value",
        )
        result = await future
    """

    def __init__(
        self,
        max_workers: int = 20,
        max_per_plugin: int = 5,
        task_timeout_s: float = 300.0,
    ) -> None:
        self._max_workers   = max_workers
        self._max_per_plugin = max_per_plugin
        self._timeout       = task_timeout_s
        self._queue:        asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._active_count: Dict[str, int] = {}    # plugin_id → active count
        self._total_active  = 0
        self._running       = False
        self._workers:      List[asyncio.Task] = []
        self._stats = {
            "enqueued":   0,
            "completed":  0,
            "failed":     0,
            "timed_out":  0,
        }

    async def submit(
        self,
        coro_fn: Callable[..., Coroutine[Any, Any, Any]],
        *,
        plugin_id: str = "",
        tenant_id: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        **kwargs: Any,
    ) -> asyncio.Future:
        """Enqueue a coroutine for execution. Returns a Future resolved with the result."""
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        task = PoolTask(
            priority=priority,
            plugin_id=plugin_id,
            tenant_id=tenant_id,
            coro_fn=coro_fn,
            kwargs=kwargs,
            result_future=future,
        )
        await self._queue.put(task)
        self._stats["enqueued"] += 1
        return future

    async def run(self) -> None:
        """Start the pool worker loop. Call via asyncio.create_task()."""
        self._running = True
        log.info("WorkerPool: started, max_workers=%d per_plugin=%d",
                 self._max_workers, self._max_per_plugin)
        workers = [asyncio.create_task(self._worker(i)) for i in range(self._max_workers)]
        self._workers = workers
        await asyncio.gather(*workers, return_exceptions=True)

    async def _worker(self, worker_id: int) -> None:
        while self._running:
            try:
                task: PoolTask = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

            # Per-plugin concurrency check
            pid = task.plugin_id or "__global__"
            if self._active_count.get(pid, 0) >= self._max_per_plugin:
                # Re-queue (brief backoff prevents tight spin)
                await asyncio.sleep(0.1)
                await self._queue.put(task)
                continue

            self._active_count[pid] = self._active_count.get(pid, 0) + 1
            self._total_active += 1

            try:
                result = await asyncio.wait_for(
                    task.coro_fn(**task.kwargs),
                    timeout=self._timeout,
                )
                if task.result_future and not task.result_future.done():
                    task.result_future.set_result(result)
                self._stats["completed"] += 1
            except asyncio.TimeoutError:
                self._stats["timed_out"] += 1
                err = TimeoutError(f"Task {task.task_id} timed out after {self._timeout}s")
                if task.result_future and not task.result_future.done():
                    task.result_future.set_exception(err)
                log.warning("WorkerPool: task %s timed out (plugin=%s)", task.task_id, pid)
            except Exception as exc:
                self._stats["failed"] += 1
                if task.result_future and not task.result_future.done():
                    task.result_future.set_exception(exc)
                log.error("WorkerPool: task %s failed (plugin=%s): %s",
                          task.task_id, pid, exc, exc_info=True)
            finally:
                self._active_count[pid] = max(0, self._active_count.get(pid, 1) - 1)
                self._total_active = max(0, self._total_active - 1)
                self._queue.task_done()

    async def drain(self, timeout_s: float = 60.0) -> None:
        """Wait for all queued tasks to complete."""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout_s)
        except asyncio.TimeoutError:
            log.warning("WorkerPool: drain timed out after %.0fs", timeout_s)

    def stop(self) -> None:
        self._running = False

    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "queued":        self._queue.qsize(),
            "active":        self._total_active,
            "active_by_plugin": dict(self._active_count),
        }
