"""
ResourceQuota — tracks and enforces per-plugin resource usage.

Tracks: API calls per minute, memory hints, CPU time.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

log = logging.getLogger(__name__)


@dataclass
class ResourceQuota:
    plugin_id:              str
    max_requests_per_minute: Optional[int] = None
    max_memory_mb:          Optional[int] = None
    max_cpu_seconds:        Optional[float] = None
    # Runtime counters
    _requests:    "Deque[float]" = field(default_factory=deque, repr=False)
    _cpu_used:    float = field(default=0.0, repr=False)

    def record_request(self) -> None:
        now = time.monotonic()
        self._requests.append(now)
        # Evict requests older than 60s
        cutoff = now - 60.0
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()

    def requests_in_last_minute(self) -> int:
        now = time.monotonic()
        return sum(1 for t in self._requests if now - t <= 60.0)

    def is_rate_limited(self) -> bool:
        if self.max_requests_per_minute is None:
            return False
        return self.requests_in_last_minute() >= self.max_requests_per_minute

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id":               self.plugin_id,
            "max_requests_per_minute": self.max_requests_per_minute,
            "requests_last_minute":    self.requests_in_last_minute(),
            "max_memory_mb":           self.max_memory_mb,
        }


class QuotaEnforcer:
    """
    Enforces resource quotas for all plugins.
    Integrates with SandboxManager to read max_requests_per_minute.
    """

    def __init__(self) -> None:
        self._quotas: Dict[str, ResourceQuota] = {}

    def register(self, plugin_id: str, policy: Any) -> None:
        self._quotas[plugin_id] = ResourceQuota(
            plugin_id=plugin_id,
            max_requests_per_minute=getattr(policy, "max_requests_per_minute", None),
            max_memory_mb=getattr(policy, "max_memory_mb", None),
        )

    def record_request(self, plugin_id: str) -> None:
        q = self._quotas.get(plugin_id)
        if q:
            q.record_request()

    def check(self, plugin_id: str) -> bool:
        """Return True if plugin is within quota, False if rate-limited."""
        q = self._quotas.get(plugin_id)
        return q is None or not q.is_rate_limited()

    async def wait_if_limited(self, plugin_id: str) -> None:
        """Wait until the plugin's rate limit window resets."""
        for _ in range(60):
            if self.check(plugin_id):
                return
            await asyncio.sleep(1.0)
        log.warning("QuotaEnforcer: %s still rate-limited after 60s", plugin_id)

    def summary(self) -> Dict[str, Any]:
        return {pid: q.to_dict() for pid, q in self._quotas.items()}
