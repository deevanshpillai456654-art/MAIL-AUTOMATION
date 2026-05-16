"""Provider-aware authentication recovery orchestration."""
from __future__ import annotations
from typing import Dict
from backend.db.database import Database
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.auth.oauth_recovery_engine import OAuthRecoveryEngine


class AuthRecoveryOrchestrator:
    def __init__(self, db: Database):
        self.db = db
        self.registry = ProviderCapabilityRegistry()
        self.oauth = OAuthRecoveryEngine(db)

    def recover_account(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        cap = self.registry.get(account.get("provider"))
        if cap.supports_oauth:
            return self.oauth.recover(account_id)
        if cap.supports_imap and not account.get("refresh_token"):
            self.db.update_account_status(account_id, "needs_reconnect", "credential_required", "Encrypted mailbox credential is missing")
            return {"ok": False, "status": "credential_required", "account_id": account_id}
        return {"ok": True, "status": "credential_present", "account_id": account_id}
