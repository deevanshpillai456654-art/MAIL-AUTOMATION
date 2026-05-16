from __future__ import annotations
from typing import Dict, List
from sdk.models import utc_now

class AuditLog:
    def __init__(self) -> None:
        self.records: List[Dict] = []

    def record(self, tenant_id: str, action: str, actor: str, entity_type: str, entity_id: str, metadata: dict | None = None) -> dict:
        rec = {"tenant_id": tenant_id, "action": action, "actor": actor, "entity_type": entity_type, "entity_id": entity_id, "metadata": metadata or {}, "created_at": utc_now()}
        self.records.append(rec)
        return rec

    def list(self, tenant_id: str) -> List[Dict]:
        return [r for r in self.records if r["tenant_id"] == tenant_id]
