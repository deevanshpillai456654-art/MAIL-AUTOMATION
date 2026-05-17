"""
QueueSDK — plugin-safe job queue access.

Usage::

    sdk = QueueSDK(context)
    job_id = sdk.enqueue("sync_contacts", {"page": 1}, max_attempts=5)
    sdk.complete(job_id)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class QueueSDK:
    """Queue operations proxied through context.queue (QueueAdapter)."""

    def __init__(self, context: Any) -> None:
        self._ctx = context

    @property
    def _queue(self) -> Optional[Any]:
        return getattr(self._ctx, "queue", None)

    def enqueue(
        self,
        job_type: str,
        payload: Dict[str, Any],
        *,
        max_attempts: int = 3,
        delay_seconds: int = 0,
        priority: int = 2,
    ) -> Optional[str]:
        if not self._queue:
            log.warning("QueueSDK: no queue adapter available")
            return None
        return self._queue.enqueue(
            job_type, payload,
            max_attempts=max_attempts,
            delay_seconds=delay_seconds,
            priority=priority,
        )

    def complete(self, job_id: str) -> None:
        if self._queue:
            self._queue.complete(job_id)

    def fail(self, job_id: str, error: str) -> None:
        if self._queue:
            self._queue.fail(job_id, error)

    def fetch_pending(self, limit: int = 10) -> List[Dict[str, Any]]:
        if not self._queue:
            return []
        return self._queue.fetch_pending(limit)
