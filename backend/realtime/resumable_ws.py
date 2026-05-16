"""
Resumable WebSocket helpers.

A tiny in-memory session wrapper used by tests and optional realtime features.
It intentionally avoids importing a non-existent nested realtime package.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class ResumableWebSocket:
    """Track outbound messages so a client can resume after reconnect."""

    session_id: str = "default"
    max_buffer: int = 1000
    connected: bool = False
    last_sequence: int = 0
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def __post_init__(self):
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=self.max_buffer)

    def connect(self) -> Dict[str, Any]:
        self.connected = True
        self.last_seen = time.time()
        return {"status": "connected", "session_id": self.session_id, "last_sequence": self.last_sequence}

    def disconnect(self) -> Dict[str, Any]:
        self.connected = False
        self.last_seen = time.time()
        return {"status": "disconnected", "session_id": self.session_id}

    def record(self, payload: Any, topic: str = "default") -> Dict[str, Any]:
        self.last_sequence += 1
        message = {
            "sequence": self.last_sequence,
            "topic": topic,
            "payload": payload,
            "timestamp": time.time(),
        }
        self._buffer.append(message)
        return message

    def resume_from(self, sequence: Optional[int] = None) -> List[Dict[str, Any]]:
        start = sequence if sequence is not None else 0
        self.last_seen = time.time()
        return [msg for msg in self._buffer if msg["sequence"] > start]

    def get_status(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "connected": self.connected,
            "last_sequence": self.last_sequence,
            "buffered": len(self._buffer),
            "last_seen": self.last_seen,
        }


__all__ = ["ResumableWebSocket"]
