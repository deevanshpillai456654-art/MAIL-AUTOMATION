"""
Shard-aware fair scheduler: per-tenant queues with round-robin dequeue.

Bounded queues reject work when pressure limits are hit (backpressure).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("dist_scheduler")


class ScheduleClass(Enum):
    BATCH = 1
    INTERACTIVE = 2
    CRITICAL = 3


@dataclass(order=True)
class ScheduledWork:
    sort_key: Tuple[int, float, str]
    work_id: str = field(compare=False)
    tenant_id: str = field(compare=False)
    shard_id: int = field(compare=False)
    payload: Dict[str, Any] = field(compare=False)


class DistributedScheduler:
    def __init__(
        self,
        max_per_tenant: int = 5000,
        global_cap: int = 50_000,
    ):
        self._max_per_tenant = max_per_tenant
        self._global_cap = global_cap
        self._queues: Dict[str, Deque[ScheduledWork]] = defaultdict(deque)
        self._heap: List[ScheduledWork] = []
        self._tenant_sizes: Dict[str, int] = defaultdict(int)
        self._total = 0
        self._lock = threading.RLock()
        self._last_service: Dict[str, float] = defaultdict(float)

    def submit(
        self,
        tenant_id: str,
        shard_id: int,
        payload: Dict[str, Any],
        sched_class: ScheduleClass = ScheduleClass.BATCH,
    ) -> str:
        work_id = f"w_{uuid.uuid4().hex[:12]}"
        pri = sched_class.value
        sw = ScheduledWork(
            sort_key=(-pri, time.time(), work_id),
            work_id=work_id,
            tenant_id=tenant_id,
            shard_id=shard_id,
            payload=payload,
        )
        with self._lock:
            if self._total >= self._global_cap:
                raise RuntimeError("global_schedule_cap_exceeded")
            if self._tenant_sizes[tenant_id] >= self._max_per_tenant:
                raise RuntimeError("tenant_schedule_cap_exceeded")
            self._queues[tenant_id].append(sw)
            self._tenant_sizes[tenant_id] += 1
            self._total += 1
        return work_id

    def _next_tenant_fair(self, tenants: List[str]) -> Optional[str]:
        if not tenants:
            return None
        tenants = sorted(tenants, key=lambda t: (self._last_service[t], t))
        return tenants[0]

    def pop_next(self) -> Optional[ScheduledWork]:
        with self._lock:
            tenants = [t for t, q in self._queues.items() if q]
            tenant = self._next_tenant_fair(tenants)
            if not tenant:
                return None
            q = self._queues[tenant]
            sw = q.popleft()
            self._tenant_sizes[tenant] -= 1
            self._total -= 1
            self._last_service[tenant] = time.time()
            if not q:
                del self._queues[tenant]
            return sw

    def depth(self) -> Dict[str, int]:
        with self._lock:
            return {t: len(q) for t, q in self._queues.items()}


__all__ = ["ScheduleClass", "ScheduledWork", "DistributedScheduler"]
