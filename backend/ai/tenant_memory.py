"""
Namespaced in-memory recall per tenant for RAG-style context (local process only).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List

logger = logging.getLogger("tenant_memory")


@dataclass
class MemoryEntry:
    key: str
    value: str
    created_at: float = field(default_factory=time.time)


class TenantMemory:
    def __init__(self, max_entries_per_tenant: int = 500):
        self._max = max_entries_per_tenant
        self._store: Dict[str, Deque[MemoryEntry]] = {}
        self._lock = threading.RLock()

    def put(self, tenant_id: str, key: str, value: str) -> None:
        with self._lock:
            q = self._store.setdefault(tenant_id, deque())
            q.append(MemoryEntry(key=key, value=value))
            while len(q) > self._max:
                q.popleft()

    def recent(self, tenant_id: str, limit: int = 20) -> List[MemoryEntry]:
        with self._lock:
            q = self._store.get(tenant_id)
            if not q:
                return []
            return list(q)[-limit:]

    def clear_tenant(self, tenant_id: str) -> None:
        with self._lock:
            self._store.pop(tenant_id, None)


__all__ = ["MemoryEntry", "TenantMemory"]
