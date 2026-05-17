"""
TenantRepository — CRUD for tenant records (platform-internal use only).

Not exposed to plugin code; used by the runtime and install systems to
manage tenant rows in the connectors DB.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class TenantRepository:
    def __init__(self, db: Any) -> None:
        self._db = db

    def create(
        self,
        name: str,
        *,
        plan: str = "free",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        tenant_id = f"t_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            """INSERT OR IGNORE INTO tenants (id, name, plan, metadata, created_at)
               VALUES (?,?,?,?,?)""",
            (tenant_id, name, plan, json.dumps(metadata or {}), now),
        )
        return tenant_id

    def get(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        row = self._db.fetch_one(
            "SELECT * FROM tenants WHERE id=?", (tenant_id,)
        )
        if not row:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return d

    def update(self, tenant_id: str, **fields: Any) -> None:
        allowed = {"name", "plan", "metadata"}
        data = {k: v for k, v in fields.items() if k in allowed}
        if not data:
            return
        if "metadata" in data and isinstance(data["metadata"], dict):
            data["metadata"] = json.dumps(data["metadata"])
        sets = ", ".join(f"{k}=?" for k in data)
        self._db.execute(
            f"UPDATE tenants SET {sets} WHERE id=?",  # nosec B608
            (*data.values(), tenant_id),
        )

    def list_all(self) -> List[Dict[str, Any]]:
        rows = self._db.fetch_all("SELECT * FROM tenants") or []
        out = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            out.append(d)
        return out
