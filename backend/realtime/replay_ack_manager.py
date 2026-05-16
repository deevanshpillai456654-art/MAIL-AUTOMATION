"""
WebSocket replay ACK checkpoints, budgets, and deduplication.

Session checkpoints live in realtime.session_checkpointing.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .session_checkpointing import SessionCheckpointManager

logger = logging.getLogger("replay_ack")


@dataclass
class ReplayACK:
    ack_id: str
    event_id: str
    session_id: str
    received_at: float
    processed: bool = False


@dataclass
class ReplayBudget:
    source_id: str
    max_per_minute: int = 100
    current_count: int = 0
    window_start: float = field(default_factory=time.time)


class ReplayACKManager:
    def __init__(self):
        self._acks: Dict[str, ReplayACK] = {}
        self._session_tokens: Dict[str, str] = {}
        self._budgets: Dict[str, ReplayBudget] = {}
        self._dedupe: Set[str] = set()
        self._lock = threading.RLock()
        self._config = {
            "ack_timeout": 300,
            "max_dedupe": 10000,
            "budget_window": 60,
        }
        logger.info("Replay ACK manager initialized")

    def create_ack(self, event_id: str, session_id: str) -> str:
        ack_id = f"ack_{uuid.uuid4().hex[:12]}"
        with self._lock:
            dedupe_key = f"{session_id}:{event_id}"
            if dedupe_key in self._dedupe:
                logger.warning("Duplicate replay event for session: %s", dedupe_key)
                return ""
            ack = ReplayACK(
                ack_id=ack_id,
                event_id=event_id,
                session_id=session_id,
                received_at=time.time(),
            )
            self._acks[ack_id] = ack
            self._dedupe.add(dedupe_key)
            if len(self._dedupe) > self._config["max_dedupe"]:
                keep = self._config["max_dedupe"] // 2
                self._dedupe = set(list(self._dedupe)[-keep:])
            return ack_id

    def acknowledge(self, ack_id: str) -> bool:
        with self._lock:
            if ack_id in self._acks:
                self._acks[ack_id].processed = True
                return True
            return False

    def get_pending(self, session_id: str) -> List[str]:
        with self._lock:
            return [
                ack.event_id
                for ack in self._acks.values()
                if ack.session_id == session_id and not ack.processed
            ]

    def cleanup_old(self, max_age: float = 3600):
        with self._lock:
            now = time.time()
            to_remove = [
                aid for aid, ack in self._acks.items() if now - ack.received_at > max_age
            ]
            for aid in to_remove:
                del self._acks[aid]

    def get_continuation_token(self, session_id: str) -> str:
        with self._lock:
            if session_id in self._session_tokens:
                return self._session_tokens[session_id]
            token = hashlib.sha256(f"{session_id}:{time.time()}".encode()).hexdigest()
            self._session_tokens[session_id] = token
            return token

    def check_budget(self, source_id: str) -> bool:
        with self._lock:
            if source_id not in self._budgets:
                self._budgets[source_id] = ReplayBudget(source_id=source_id)
            budget = self._budgets[source_id]
            now = time.time()
            if now - budget.window_start > self._config["budget_window"]:
                budget.window_start = now
                budget.current_count = 0
            if budget.current_count >= budget.max_per_minute:
                return False
            budget.current_count += 1
            return True


_global_ack_manager: Optional[ReplayACKManager] = None
_global_checkpoint_manager: Optional[SessionCheckpointManager] = None


def get_replay_ack_manager() -> ReplayACKManager:
    global _global_ack_manager
    if _global_ack_manager is None:
        _global_ack_manager = ReplayACKManager()
    return _global_ack_manager


def get_checkpoint_manager() -> SessionCheckpointManager:
    global _global_checkpoint_manager
    if _global_checkpoint_manager is None:
        _global_checkpoint_manager = SessionCheckpointManager()
    return _global_checkpoint_manager


__all__ = [
    "ReplayACK",
    "ReplayBudget",
    "ReplayACKManager",
    "SessionCheckpointManager",
    "get_replay_ack_manager",
    "get_checkpoint_manager",
]
