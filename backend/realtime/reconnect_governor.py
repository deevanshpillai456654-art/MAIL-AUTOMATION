"""
Limits reconnect and replay storms with token buckets and circuit breaking.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple

logger = logging.getLogger("reconnect_governor")


@dataclass
class GovernorConfig:
    max_connects_per_minute: int = 30
    max_replay_events_per_minute: int = 200
    open_circuit_seconds: float = 60.0
    jitter_ms: Tuple[int, int] = (50, 400)


@dataclass
class _Window:
    window_start: float = field(default_factory=time.time)
    connects: int = 0
    replays: int = 0


class ReconnectGovernor:
    def __init__(self, config: GovernorConfig | None = None):
        self._cfg = config or GovernorConfig()
        self._sessions: Dict[str, _Window] = {}
        self._circuit_open_until: Dict[str, float] = {}
        self._lock = threading.RLock()

    def _window(self, session_id: str) -> _Window:
        if session_id not in self._sessions:
            self._sessions[session_id] = _Window()
        w = self._sessions[session_id]
        now = time.time()
        if now - w.window_start > 60.0:
            w.window_start = now
            w.connects = 0
            w.replays = 0
        return w

    def allow_connect(self, session_id: str) -> Tuple[bool, str]:
        with self._lock:
            now = time.time()
            if self._circuit_open_until.get(session_id, 0) > now:
                return False, "circuit_open"
            w = self._window(session_id)
            if w.connects >= self._cfg.max_connects_per_minute:
                self._circuit_open_until[session_id] = now + self._cfg.open_circuit_seconds
                logger.warning("Reconnect storm for session %s; circuit open", session_id)
                return False, "connect_budget_exceeded"
            w.connects += 1
            return True, "ok"

    def allow_replay(self, session_id: str, event_count: int = 1) -> Tuple[bool, str]:
        with self._lock:
            now = time.time()
            if self._circuit_open_until.get(session_id, 0) > now:
                return False, "circuit_open"
            w = self._window(session_id)
            if w.replays + event_count > self._cfg.max_replay_events_per_minute:
                self._circuit_open_until[session_id] = now + self._cfg.open_circuit_seconds
                return False, "replay_budget_exceeded"
            w.replays += event_count
            return True, "ok"

    def backoff_delay_ms(self) -> float:
        lo, hi = self._cfg.jitter_ms
        return random.uniform(lo, hi)

    def reset_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)
            self._circuit_open_until.pop(session_id, None)


__all__ = ["GovernorConfig", "ReconnectGovernor"]
