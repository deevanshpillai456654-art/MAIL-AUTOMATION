"""
Idempotent operation keys with TTL for API and worker handlers.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("idempotency")


class IdempotencyManager:
    def __init__(self, _db: Optional[Any] = None, ttl_seconds: float = 3600.0):
        self._db = _db
        self._ttl_seconds = ttl_seconds
        self._processed: Dict[str, Dict[str, float]] = {}
        self._lock = threading.RLock()

    def generate_idempotency_key(
        self,
        event_type: str,
        email_id: str,
        timestamp: Optional[datetime] = None,
    ) -> str:
        del timestamp
        raw = f"{event_type}:{email_id}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def is_processed(self, event_id: str) -> bool:
        with self._lock:
            rec = self._processed.get(event_id)
            if not rec:
                return False
            if time.time() - rec["timestamp"] > self._ttl_seconds:
                del self._processed[event_id]
                return False
            return True

    def mark_processed(self, event_id: str) -> None:
        with self._lock:
            self._processed[event_id] = {"timestamp": time.time()}

    def cleanup_expired(self) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            expired = [k for k, v in self._processed.items() if now - v["timestamp"] > self._ttl_seconds]
            for k in expired:
                del self._processed[k]
                removed += 1
        return removed


__all__ = ["IdempotencyManager"]
