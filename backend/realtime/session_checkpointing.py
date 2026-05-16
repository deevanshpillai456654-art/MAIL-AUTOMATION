"""
Durable session checkpoints for WebSocket and streaming clients.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("session_checkpoint")


class SessionCheckpointManager:
    def __init__(self, max_checkpoints: int = 10_000):
        self._checkpoints: Dict[str, Dict[str, Any]] = {}
        self._max = max_checkpoints
        self._lock = threading.RLock()

    def create_checkpoint(self, session_id: str, state: Dict[str, Any]) -> str:
        checkpoint_id = f"cp_{uuid.uuid4().hex[:12]}"
        with self._lock:
            if len(self._checkpoints) >= self._max:
                oldest = min(self._checkpoints.values(), key=lambda x: x["created_at"])
                self._checkpoints.pop(oldest["checkpoint_id"], None)
            self._checkpoints[checkpoint_id] = {
                "checkpoint_id": checkpoint_id,
                "session_id": session_id,
                "state": dict(state),
                "created_at": time.time(),
            }
        return checkpoint_id

    def get_checkpoint(self, checkpoint_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            cp = self._checkpoints.get(checkpoint_id)
            return dict(cp) if cp else None

    def get_latest(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            checkpoints = [cp for cp in self._checkpoints.values() if cp["session_id"] == session_id]
            if not checkpoints:
                return None
            latest = max(checkpoints, key=lambda x: x["created_at"])
            return dict(latest)

    def list_session_ids(self) -> List[str]:
        with self._lock:
            return list({cp["session_id"] for cp in self._checkpoints.values()})


__all__ = ["SessionCheckpointManager"]
