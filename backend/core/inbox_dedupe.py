"""
Inbox pattern: idempotent consumer-side deduplication with bounded memory.

Prevents duplicate handling when the same message is redelivered.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Tuple

logger = logging.getLogger("inbox_dedupe")


class InboxDeduper:
    def __init__(self, max_entries: int = 100_000, ttl_seconds: float = 86400.0):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.RLock()

    def _evict_expired(self, now: float) -> None:
        keys = [k for k, ts in self._seen.items() if now - ts > self._ttl]
        for k in keys:
            self._seen.pop(k, None)

    def _trim(self) -> None:
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)

    def should_process(self, message_id: str) -> Tuple[bool, str]:
        now = time.time()
        with self._lock:
            self._evict_expired(now)
            if message_id in self._seen:
                return False, "duplicate"
            self._seen[message_id] = now
            self._seen.move_to_end(message_id)
            self._trim()
            return True, "first_seen"

    def ack_processed(self, message_id: str) -> None:
        """Optional: refresh TTL for active idempotency window."""
        with self._lock:
            if message_id in self._seen:
                self._seen[message_id] = time.time()


__all__ = ["InboxDeduper"]
