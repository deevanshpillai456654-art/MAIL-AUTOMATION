"""Mailbox health scoring and account-safe diagnostics."""
from __future__ import annotations

from typing import Dict, List

from backend.auth.provider_auth_health import ProviderAuthHealth
from backend.core.provider_reliability_engine import ProviderReliabilityEngine
from backend.db.database import Database


class MailboxHealthEngine:
    def __init__(self, db: Database):
        self.db = db
        self.auth = ProviderAuthHealth(db)
        self.reliability = ProviderReliabilityEngine(db)

    def account_health(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        auth = self.auth.account(account_id)
        reliability = self.reliability.score_account(account_id)
        ok = bool(auth.get("ok")) and bool(reliability.get("ok")) and account.get("status") != "paused"
        return {
            "ok": ok,
            "status": "healthy" if ok else account.get("status") or auth.get("status") or reliability.get("status"),
            "account_id": account_id,
            "provider": account.get("provider"),
            "email": account.get("email"),
            "auth": auth,
            "reliability": reliability,
        }

    def all_health(self) -> List[Dict]:
        return [self.account_health(row["id"]) for row in self.db.get_all_accounts()]
