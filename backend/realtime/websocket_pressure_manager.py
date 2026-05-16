"""Websocket pressure governor for queue and payload growth."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class PressureState:
    queued_messages: int = 0
    queued_bytes: int = 0
    dropped_messages: int = 0


class WebsocketPressureManager:
    def __init__(self, max_messages: int = 1000, max_bytes: int = 5_000_000):
        self.max_messages = max_messages
        self.max_bytes = max_bytes
        self._states: Dict[str, PressureState] = {}
        self._lock = threading.RLock()

    def reserve(self, session_id: str, payload_bytes: int) -> Tuple[bool, str]:
        with self._lock:
            state = self._states.setdefault(session_id, PressureState())
            if state.queued_messages + 1 > self.max_messages or state.queued_bytes + payload_bytes > self.max_bytes:
                state.dropped_messages += 1
                return False, "websocket_pressure_limit"
            state.queued_messages += 1
            state.queued_bytes += max(0, payload_bytes)
            return True, "reserved"

    def release(self, session_id: str, payload_bytes: int) -> None:
        with self._lock:
            state = self._states.setdefault(session_id, PressureState())
            state.queued_messages = max(0, state.queued_messages - 1)
            state.queued_bytes = max(0, state.queued_bytes - max(0, payload_bytes))

    def state(self, session_id: str) -> PressureState:
        with self._lock:
            return self._states.setdefault(session_id, PressureState())


__all__ = ["PressureState", "WebsocketPressureManager"]
