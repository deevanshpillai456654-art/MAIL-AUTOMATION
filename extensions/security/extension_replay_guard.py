"""Bounded replay guard for extension and cross-tab requests."""
from __future__ import annotations

from collections import deque

class ExtensionReplayGuard:
    def __init__(self, max_entries: int = 5000):
        self.max_entries = int(max_entries)
        self._seen: set[str] = set()
        self._order: deque[str] = deque()

    def accept(self, tenant_id: str, account_id: str, nonce: str) -> bool:
        key = f"{tenant_id}:{account_id}:{nonce}"
        if key in self._seen:
            return False
        self._seen.add(key)
        self._order.append(key)
        while len(self._order) > self.max_entries:
            self._seen.discard(self._order.popleft())
        return True
