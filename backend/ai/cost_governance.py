"""
Token and request budgets per tenant with sliding window counters.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

logger = logging.getLogger("cost_governance")


class CostGovernor:
    def __init__(self, window_sec: float = 3600.0):
        self._window = window_sec
        self._usage: Dict[str, Deque[Tuple[float, int]]] = {}
        self._caps: Dict[str, int] = {}
        self._lock = threading.RLock()

    def set_cap(self, tenant_id: str, max_tokens_per_window: int) -> None:
        with self._lock:
            self._caps[tenant_id] = max_tokens_per_window
            self._usage.setdefault(tenant_id, deque())

    def _prune(self, tenant_id: str, now: float) -> None:
        q = self._usage.setdefault(tenant_id, deque())
        while q and now - q[0][0] > self._window:
            q.popleft()

    def allow(self, tenant_id: str, tokens: int) -> Tuple[bool, str]:
        with self._lock:
            now = time.time()
            cap = self._caps.get(tenant_id)
            if cap is None:
                return True, "no_cap"
            self._prune(tenant_id, now)
            used = sum(t for _, t in self._usage[tenant_id])
            if used + tokens > cap:
                logger.info("Cost cap exceeded tenant=%s used=%s cap=%s", tenant_id, used, cap)
                return False, "budget_exceeded"
            self._usage[tenant_id].append((now, tokens))
            return True, "ok"


__all__ = ["CostGovernor"]
