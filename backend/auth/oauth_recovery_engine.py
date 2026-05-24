"""OAuth recovery decisions that avoid reconnect storms."""
from __future__ import annotations

from typing import Dict

from backend.auth.provider_token_manager import ProviderTokenManager
from backend.db.database import Database


class OAuthRecoveryEngine:
    def __init__(self, db: Database):
        self.db = db
        self.tokens = ProviderTokenManager(db)

    def recover(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        health = self.tokens.token_health(account_id)
        if health.get("status") in {"expired", "refresh_recommended"}:
            result = self.tokens.get_valid_access_token(account_id)
            return {"ok": bool(result), "status": "refreshed" if result else "needs_reconnect", "account_id": account_id}
        if health.get("status") == "needs_reconnect":
            self.db.update_account_status(account_id, "needs_reconnect", "consent_required", "OAuth consent or refresh token is required")
            return {"ok": False, "status": "consent_required", "account_id": account_id}
        return {"ok": bool(health.get("ok")), "status": health.get("status"), "account_id": account_id}
