"""Mailbox-scoped websocket namespace helpers."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, Set


@dataclass
class MailboxSubscription:
    session_id: str
    tenant_id: int
    account_id: int
    provider: str
    topics: Set[str] = field(default_factory=set)

    @property
    def namespace(self) -> str:
        return f"tenant:{self.tenant_id}:account:{self.account_id}:provider:{self.provider}"


class MailboxWebSocketNamespace:
    def __init__(self):
        self._subscriptions: Dict[str, MailboxSubscription] = {}
        self._lock = threading.RLock()

    def subscribe(self, session_id: str, tenant_id: int, account_id: int, provider: str, topic: str = "mailbox") -> Dict:
        with self._lock:
            sub = self._subscriptions.get(session_id) or MailboxSubscription(session_id, tenant_id, account_id, provider)
            sub.topics.add(topic)
            self._subscriptions[session_id] = sub
            return {"ok": True, "namespace": sub.namespace, "topics": sorted(sub.topics)}

    def unsubscribe(self, session_id: str) -> Dict:
        with self._lock:
            sub = self._subscriptions.pop(session_id, None)
            return {"ok": bool(sub), "namespace": sub.namespace if sub else None}

    def sessions_for(self, tenant_id: int, account_id: int, provider: str) -> Set[str]:
        namespace = f"tenant:{tenant_id}:account:{account_id}:provider:{provider}"
        with self._lock:
            return {sid for sid, sub in self._subscriptions.items() if sub.namespace == namespace}

    def cleanup_account(self, account_id: int) -> int:
        with self._lock:
            stale = [sid for sid, sub in self._subscriptions.items() if sub.account_id == account_id]
            for sid in stale:
                self._subscriptions.pop(sid, None)
            return len(stale)
