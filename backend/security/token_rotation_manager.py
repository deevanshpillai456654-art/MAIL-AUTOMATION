"""Local token rotation policy helpers."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict

from backend.db.database import Database


class TokenRotationManager:
    def __init__(self, db: Database, max_age_days: int = 30):
        self.db = db
        self.max_age_days = max_age_days

    def rotation_due(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        updated = account.get("updated_at") or account.get("created_at")
        try:
            ts = datetime.fromisoformat(updated)
        except Exception:
            ts = datetime.now() - timedelta(days=self.max_age_days + 1)
        due = ts < datetime.now() - timedelta(days=self.max_age_days)
        return {"ok": True, "status": "rotation_due" if due else "fresh", "due": due, "account_id": account_id}
