"""
Session manager for the AI assistant.

Tracks per-user troubleshooting sessions in memory.  Sessions expire after
SESSION_TTL_SECONDS of inactivity and are cleaned up lazily on next access.
No persistence is needed — sessions are ephemeral troubleshooting contexts.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SESSION_TTL_SECONDS = 1800  # 30 minutes


@dataclass
class AssistantSession:
    session_id: str
    mode: str                               # "user" | "admin"
    issue_id: Optional[str] = None          # currently active issue flow
    step_index: int = 0                     # 0-based current step
    context: Dict[str, Any] = field(default_factory=dict)   # diagnostics snapshot
    history: List[Dict[str, Any]] = field(default_factory=list)
    actions_taken: List[Dict[str, Any]] = field(default_factory=list)
    completed_flows: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.last_activity = time.time()

    def is_expired(self) -> bool:
        return (time.time() - self.last_activity) > SESSION_TTL_SECONDS

    def record_action(self, action_id: str, result: Dict[str, Any]) -> None:
        self.actions_taken.append({
            "action_id": action_id,
            "result": result,
            "at": time.time(),
        })

    def add_history(self, event: str, data: Dict[str, Any] | None = None) -> None:
        self.history.append({"event": event, "data": data or {}, "at": time.time()})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "mode": self.mode,
            "issue_id": self.issue_id,
            "step_index": self.step_index,
            "actions_taken": len(self.actions_taken),
            "completed_flows": self.completed_flows,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "age_seconds": round(time.time() - self.created_at),
        }


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, AssistantSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, mode: str = "user", context: Dict[str, Any] | None = None) -> AssistantSession:
        async with self._lock:
            self._evict_expired()
            session_id = str(uuid.uuid4())
            session = AssistantSession(
                session_id=session_id,
                mode=mode,
                context=context or {},
            )
            self._sessions[session_id] = session
            return session

    async def get(self, session_id: str) -> Optional[AssistantSession]:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.is_expired():
                del self._sessions[session_id]
                return None
            session.touch()
            return session

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_expired(self) -> None:
        expired = [sid for sid, s in self._sessions.items() if s.is_expired()]
        for sid in expired:
            del self._sessions[sid]

    def active_count(self) -> int:
        self._evict_expired()
        return len(self._sessions)


_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
