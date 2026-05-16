"""Websocket session continuation tokens and cursors."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class SessionContinuation:
    session_id: str
    scope_key: str
    cursor: Optional[str]
    token: str
    updated_at: float = field(default_factory=time.time)


class SessionContinuationManager:
    def __init__(self, secret: str | None = None):
        self._secret = (secret or secrets.token_hex(32)).encode("utf-8")
        self._sessions: Dict[str, SessionContinuation] = {}
        self._lock = threading.RLock()

    def issue(self, session_id: str, scope_key: str, cursor: Optional[str] = None) -> SessionContinuation:
        message = f"{session_id}:{scope_key}:{cursor or ''}:{time.time()}".encode("utf-8")
        token = hmac.new(self._secret, message, hashlib.sha256).hexdigest()
        continuation = SessionContinuation(session_id, scope_key, cursor, token)
        with self._lock:
            self._sessions[token] = continuation
        return continuation

    def resume(self, token: str, max_age_seconds: float = 3600.0) -> Optional[SessionContinuation]:
        with self._lock:
            item = self._sessions.get(token)
            if not item or time.time() - item.updated_at > max_age_seconds:
                return None
            item.updated_at = time.time()
            return item


__all__ = ["SessionContinuation", "SessionContinuationManager"]
