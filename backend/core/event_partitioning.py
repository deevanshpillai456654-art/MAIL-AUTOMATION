"""
Logical stream partitioning by tenant and optional secondary key.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Dict, List

logger = logging.getLogger("event_partition")


class EventPartitioner:
    def __init__(self, partition_count: int = 32):
        self._n = max(1, partition_count)
        self._routing: Dict[str, int] = {}
        self._lock = threading.Lock()

    def partition_for(self, tenant_id: str, key: str = "") -> int:
        raw = f"{tenant_id}:{key}".encode("utf-8")
        return int(hashlib.sha256(raw).hexdigest(), 16) % self._n

    def assign_stream(self, stream_id: str, tenant_id: str, key: str = "") -> int:
        part = self.partition_for(tenant_id, key)
        with self._lock:
            self._routing[stream_id] = part
        return part

    def streams_on_partition(self, partition: int) -> List[str]:
        with self._lock:
            return [sid for sid, p in self._routing.items() if p == partition]


__all__ = ["EventPartitioner"]
