"""
Idempotency Manager
==================

Manages event idempotency keys.
"""

import threading
import time
from collections import deque
from typing import Optional, Set


class IdempotencyManager:
    """
    Idempotency key manager.
    """

    def __init__(self, max_keys: int = 10000, ttl_seconds: float = 86400):
        self.max_keys = max_keys
        self.ttl_seconds = ttl_seconds
        self._keys: Set[str] = set()
        self._timestamps: deque = deque()
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Check if key is idempotent"""
        with self._lock:
            return key in self._keys

    def add(self, key: str):
        """Add idempotency key"""
        with self._lock:
            self._keys.add(key)
            self._timestamps.append((key, time.time()))

            # Clean expired
            self._clean()

    def _clean(self):
        """Clean expired keys"""
        now = time.time()
        while self._timestamps:
            key, ts = self._timestamps[0]
            if now - ts > self.ttl_seconds:
                self._keys.discard(key)
                self._timestamps.popleft()
            else:
                break

        # Limit size
        while len(self._keys) > self.max_keys:
            if self._timestamps:
                key, _ = self._timestamps.popleft()
                self._keys.discard(key)


_idempotency_manager: Optional[IdempotencyManager] = None


def get_idempotency_manager() -> IdempotencyManager:
    """Get global idempotency manager"""
    global _idempotency_manager
    if _idempotency_manager is None:
        _idempotency_manager = IdempotencyManager()
    return _idempotency_manager


__all__ = ["IdempotencyManager", "get_idempotency_manager"]
