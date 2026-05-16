"""Replay-safe cross-platform synchronization engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

@dataclass
class SyncDecision:
    applied: bool
    reason: str = "applied"
    sequence: int = 0

@dataclass
class CrossPlatformSyncEngine:
    """Coordinates client events without trusting any client as authoritative."""
    max_events_per_scope: int = 2000
    _last_sequence: Dict[Tuple[str, str, str], int] = field(default_factory=dict)
    _seen_events: Dict[Tuple[str, str, str], list[str]] = field(default_factory=dict)

    def apply_event(self, tenant_id: str, account_id: str, device_id: str, event: Dict[str, Any]) -> SyncDecision:
        scope = (str(tenant_id), str(account_id), str(device_id))
        event_id = str(event.get("event_id") or event.get("id") or "")
        sequence = int(event.get("sequence") or 0)
        if not event_id:
            return SyncDecision(False, "event_id_required")
        seen = self._seen_events.setdefault(scope, [])
        if event_id in seen:
            return SyncDecision(False, "duplicate_event", sequence)
        last = self._last_sequence.get(scope, 0)
        if sequence and sequence <= last:
            return SyncDecision(False, "stale_sequence", sequence)
        seen.append(event_id)
        del seen[: max(0, len(seen) - self.max_events_per_scope)]
        if sequence:
            self._last_sequence[scope] = sequence
        return SyncDecision(True, "applied", sequence)

    def checkpoint(self) -> Dict[str, Any]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scopes": len(self._last_sequence),
            "max_events_per_scope": self.max_events_per_scope,
        }
