"""Realtime state reconciliation for mailbox-scoped UI snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ReconciliationResult:
    accepted: Dict
    conflicts: List[str]
    stale: bool


class RealtimeReconciliationEngine:
    def reconcile(self, current: Dict, incoming: Dict) -> ReconciliationResult:
        conflicts: List[str] = []
        current_version = int(current.get("version", 0))
        incoming_version = int(incoming.get("version", 0))
        if incoming_version < current_version:
            return ReconciliationResult(accepted=dict(current), conflicts=["stale_version"], stale=True)
        accepted = dict(current)
        for key, value in incoming.items():
            if key in current and current[key] != value and key not in {"version", "updated_at"}:
                conflicts.append(key)
            accepted[key] = value
        return ReconciliationResult(accepted=accepted, conflicts=conflicts, stale=False)


__all__ = ["ReconciliationResult", "RealtimeReconciliationEngine"]
