"""Mailbox-scoped replay governance for multi-account realtime flows."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
import hashlib
import time
import threading


@dataclass
class MailboxReplayEvent:
    tenant_id: int
    account_id: int
    provider: str
    event_id: str
    payload_hash: str
    created_at: float = field(default_factory=time.time)

    @property
    def scope(self) -> str:
        return f"tenant:{self.tenant_id}:account:{self.account_id}:provider:{self.provider}"

    @property
    def dedupe_key(self) -> str:
        return f"{self.scope}:{self.event_id}:{self.payload_hash}"


class MailboxReplayGovernance:
    def __init__(self, max_events_per_scope: int = 1000):
        self.max_events_per_scope = max_events_per_scope
        self._seen: Dict[str, List[str]] = {}
        self._set: Set[str] = set()
        self._lock = threading.RLock()

    @staticmethod
    def payload_hash(payload: Dict) -> str:
        material = repr(sorted((payload or {}).items()))
        return hashlib.sha256(material.encode()).hexdigest()

    def accept(self, tenant_id: int, account_id: int, provider: str, event_id: str, payload: Dict) -> Dict:
        event = MailboxReplayEvent(tenant_id, account_id, provider, str(event_id), self.payload_hash(payload))
        with self._lock:
            if event.dedupe_key in self._set:
                return {"ok": False, "status": "duplicate_replay", "scope": event.scope, "event_id": event.event_id}
            self._set.add(event.dedupe_key)
            events = self._seen.setdefault(event.scope, [])
            events.append(event.dedupe_key)
            while len(events) > self.max_events_per_scope:
                old = events.pop(0)
                self._set.discard(old)
            return {"ok": True, "status": "accepted", "scope": event.scope, "event_id": event.event_id}

    def scope_key(self, tenant_id: int, account_id: int, provider: str) -> str:
        return f"tenant:{tenant_id}:account:{account_id}:provider:{provider}"


_global_mailbox_replay_governance: Optional[MailboxReplayGovernance] = None


def get_mailbox_replay_governance() -> MailboxReplayGovernance:
    global _global_mailbox_replay_governance
    if _global_mailbox_replay_governance is None:
        _global_mailbox_replay_governance = MailboxReplayGovernance()
    return _global_mailbox_replay_governance
