"""Account-scoped replay windows for websocket continuation."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


@dataclass
class ReplayWindow:
    scope_key: str
    max_events: int = 1000
    events: Deque[dict] = field(default_factory=deque)
    updated_at: float = field(default_factory=time.time)


class ReplayWindowManager:
    def __init__(self, default_max_events: int = 1000):
        self.default_max_events = default_max_events
        self._windows: Dict[str, ReplayWindow] = {}
        self._lock = threading.RLock()

    def append(self, scope_key: str, event: dict) -> None:
        with self._lock:
            window = self._windows.setdefault(scope_key, ReplayWindow(scope_key, self.default_max_events))
            window.events.append(dict(event))
            window.updated_at = time.time()
            while len(window.events) > window.max_events:
                window.events.popleft()

    def after(self, scope_key: str, cursor: Optional[str] = None, limit: int = 250) -> List[dict]:
        with self._lock:
            window = self._windows.get(scope_key)
            if not window:
                return []
            events = list(window.events)
        if cursor:
            for idx, event in enumerate(events):
                if str(event.get("event_id") or event.get("id")) == str(cursor):
                    events = events[idx + 1:]
                    break
        return events[: max(1, limit)]

    def trim_inactive(self, max_age_seconds: float = 3600.0) -> int:
        now = time.time()
        with self._lock:
            stale = [key for key, window in self._windows.items() if now - window.updated_at > max_age_seconds]
            for key in stale:
                self._windows.pop(key, None)
            return len(stale)


__all__ = ["ReplayWindow", "ReplayWindowManager"]
