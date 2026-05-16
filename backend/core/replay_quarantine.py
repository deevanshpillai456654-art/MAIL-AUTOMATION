"""Replay quarantine store for unsafe events."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class QuarantinedReplay:
    event_id: str
    scope_key: str
    reason: str
    payload: Dict[str, Any]
    quarantined_at: float = field(default_factory=time.time)
    released_at: Optional[float] = None
    released_by: Optional[str] = None


class ReplayQuarantine:
    def __init__(self):
        self._items: Dict[str, QuarantinedReplay] = {}
        self._lock = threading.RLock()

    def quarantine(self, event_id: str, scope_key: str, reason: str, payload: Dict[str, Any]) -> QuarantinedReplay:
        item = QuarantinedReplay(event_id=event_id, scope_key=scope_key, reason=reason, payload=dict(payload))
        with self._lock:
            self._items[event_id] = item
        return item

    def release(self, event_id: str, released_by: str) -> bool:
        with self._lock:
            item = self._items.get(event_id)
            if not item:
                return False
            item.released_at = time.time()
            item.released_by = released_by
            return True

    def active(self, scope_key: Optional[str] = None) -> List[QuarantinedReplay]:
        with self._lock:
            return [
                item for item in self._items.values()
                if item.released_at is None and (scope_key is None or item.scope_key == scope_key)
            ]


__all__ = ["QuarantinedReplay", "ReplayQuarantine"]
