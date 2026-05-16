"""Mailbox recovery DAG for auth, connectivity and sync failures."""
from __future__ import annotations
from typing import Dict, List
from backend.db.database import Database
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.auth.auth_recovery_orchestrator import AuthRecoveryOrchestrator


class MailboxRecoveryEngine:
    def __init__(self, db: Database):
        self.db = db
        self.auth = AuthRecoveryOrchestrator(db)
        self.registry = ProviderCapabilityRegistry()

    def diagnose(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing", "actions": []}
        diagnostic = self.db.get_latest_provider_diagnostic(account_id) or {}
        actions: List[str] = []
        reconnect_state = account.get("reconnect_state") or "ok"
        if reconnect_state in {"token_expired", "token_refresh_failed", "consent_required"}:
            actions.append("oauth_refresh_or_reconsent")
        if reconnect_state in {"credential_required", "sync_failed"} and self.registry.get(account.get("provider")).supports_imap:
            actions.append("credential_update")
        if account.get("status") == "degraded":
            actions.append("retry_with_backoff")
        return {"ok": True, "status": reconnect_state, "account_id": account_id, "diagnostic": diagnostic, "actions": actions or ["none"]}

    def recover(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        auth_result = self.auth.recover_account(account_id)
        if auth_result.get("ok"):
            self.db.update_account_status(account_id, "connected", "ok")
            return {"ok": True, "status": "recovered", "auth": auth_result}
        # Preserve explicit state for UI and orchestrator; do not loop.
        self.db.update_account_status(account_id, "needs_reconnect", auth_result.get("status") or "reconnect_required")
        return {"ok": False, "status": auth_result.get("status") or "reconnect_required", "auth": auth_result}
