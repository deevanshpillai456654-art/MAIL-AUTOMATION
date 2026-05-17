"""
TaskRunner — high-level API for running plugin tasks through the worker pool.

Wraps WorkerPool with typed task submission, retry logic, and result tracking.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, Optional

from .worker_pool import WorkerPool, TaskPriority

log = logging.getLogger(__name__)


class TaskRunner:
    """
    High-level task runner wrapping WorkerPool.

    Usage::

        runner = TaskRunner(pool)
        result = await runner.run(
            salesforce_connector.sync,
            entity="contacts",
            plugin_id="salesforce",
            tenant_id="t1",
            max_retries=3,
        )
    """

    def __init__(self, pool: WorkerPool) -> None:
        self._pool = pool

    async def run(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        *,
        plugin_id: str = "",
        tenant_id: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        max_retries: int = 0,
        retry_delay_s: float = 1.0,
        **kwargs: Any,
    ) -> Any:
        """Submit *fn(**kwargs)* to the pool, with optional retries."""
        attempts = 0
        last_exc: Optional[Exception] = None

        while attempts <= max_retries:
            future = await self._pool.submit(
                fn,
                plugin_id=plugin_id,
                tenant_id=tenant_id,
                priority=priority,
                **kwargs,
            )
            try:
                return await future
            except Exception as exc:
                last_exc = exc
                attempts += 1
                if attempts <= max_retries:
                    log.warning(
                        "TaskRunner: %s.%s failed (attempt %d/%d): %s — retrying in %.1fs",
                        plugin_id, fn.__name__, attempts, max_retries + 1, exc, retry_delay_s,
                    )
                    await asyncio.sleep(retry_delay_s * (2 ** (attempts - 1)))

        raise last_exc  # type: ignore[misc]

    async def run_sync(
        self,
        connector: Any,
        entity: str,
        *,
        plugin_id: str,
        tenant_id: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Convenience: run connector.sync(entity) through the pool."""
        return await self.run(
            connector.sync,
            plugin_id=plugin_id,
            tenant_id=tenant_id,
            entity=entity,
            **kwargs,
        )
