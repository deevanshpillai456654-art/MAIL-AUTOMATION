"""Universal mailbox orchestration layer.

The orchestrator keeps provider-specific operations behind one adapter interface
and enforces account-scoped leases, auth recovery, capability validation and
sync idempotency before mailbox work starts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Type
import logging

from backend import config
from backend.db.database import Database
from backend.core.provider_adapter_base import ProviderAdapterBase, ProviderOperationResult
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.core.mailbox_connection_manager import MailboxConnectionManager
from backend.core.mailbox_health_engine import MailboxHealthEngine
from backend.core.mailbox_recovery_engine import MailboxRecoveryEngine
from backend.core.mailbox_quarantine_engine import MailboxQuarantineEngine
from backend.core.mailbox_taxonomy import ProviderMailboxTaxonomy
from backend.auth.provider_token_manager import ProviderTokenManager
from backend.auth.imap_auth import IMAPAccountManager
from backend.sync.gmail_sync import sync_gmail_account, GmailSync
from backend.sync.outlook_sync import sync_outlook_account
from backend.sync.imap_sync import sync_imap_account

logger = logging.getLogger(__name__)


class GmailProviderAdapter(ProviderAdapterBase):
    def connect(self, account_id: int = None, **kwargs) -> ProviderOperationResult:
        return ProviderOperationResult(False, "oauth_required", self.provider, account_id, "Start Gmail OAuth to connect this mailbox.")

    def refresh_token(self, account_id: int) -> ProviderOperationResult:
        token = ProviderTokenManager(self.db).get_valid_access_token(account_id)
        return ProviderOperationResult(bool(token), "token_ok" if token else "needs_reconnect", self.provider, account_id)

    def sync(self, account_id: int, max_results: int = 50, sync_id: int = None) -> ProviderOperationResult:
        processed = sync_gmail_account(account_id, max_results, sync_id)
        diagnostic = self.db.get_latest_provider_diagnostic(account_id) or {}
        detail = {"processed": processed, "diagnostic": diagnostic}
        return ProviderOperationResult(True, "synced", self.provider, account_id, detail=detail)

    def watch(self, account_id: int) -> ProviderOperationResult:
        try:
            result = GmailSync(account_id).start_watch()
            return ProviderOperationResult(result.get("status") == "active", result.get("status", "failed"), self.provider, account_id, detail=result)
        except Exception as exc:
            return ProviderOperationResult(False, "watch_failed", self.provider, account_id, str(exc))

    def reconnect(self, account_id: int, **kwargs) -> ProviderOperationResult:
        return self.refresh_token(account_id)

    def health_check(self, account_id: int) -> ProviderOperationResult:
        health = MailboxHealthEngine(self.db).account_health(account_id)
        return ProviderOperationResult(bool(health.get("ok")), health.get("status", "unknown"), self.provider, account_id, detail=health)

    def recover(self, account_id: int) -> ProviderOperationResult:
        result = MailboxRecoveryEngine(self.db).recover(account_id)
        return ProviderOperationResult(bool(result.get("ok")), result.get("status", "recovery_failed"), self.provider, account_id, detail=result)

    def disconnect(self, account_id: int) -> ProviderOperationResult:
        self.db.update_account_status(account_id, "paused", "disconnected")
        return ProviderOperationResult(True, "disconnected", self.provider, account_id)


class OutlookProviderAdapter(GmailProviderAdapter):
    def connect(self, account_id: int = None, **kwargs) -> ProviderOperationResult:
        return ProviderOperationResult(False, "oauth_required", self.provider, account_id, "Start Microsoft OAuth to connect this mailbox.")

    def sync(self, account_id: int, max_results: int = 50, sync_id: int = None) -> ProviderOperationResult:
        processed = sync_outlook_account(account_id, max_results, sync_id)
        diagnostic = self.db.get_latest_provider_diagnostic(account_id) or {}
        detail = {"processed": processed, "diagnostic": diagnostic}
        return ProviderOperationResult(True, "synced", self.provider, account_id, detail=detail)

    def watch(self, account_id: int) -> ProviderOperationResult:
        return ProviderOperationResult(False, "configuration_required", self.provider, account_id, "Microsoft Graph webhook subscription requires a public notification URL.")


class IMAPProviderAdapter(ProviderAdapterBase):
    def connect(self, account_id: int = None, **kwargs) -> ProviderOperationResult:
        email = kwargs.get("email")
        password = kwargs.get("password")
        diagnostics = IMAPAccountManager(self.db).validate(email=email, password=password, provider=self.provider, host=kwargs.get("host"), port=kwargs.get("port"), security=kwargs.get("security"))
        if not diagnostics.get("ok"):
            return ProviderOperationResult(False, diagnostics.get("status", "connect_failed"), self.provider, account_id, diagnostics.get("message", "IMAP validation failed"), diagnostics)
        account_id = IMAPAccountManager(self.db).store_account(self.provider, email, password, diagnostics.get("metadata"))
        self.db.add_provider_diagnostic(account_id, self.provider, diagnostics.get("status", "connected"), diagnostics)
        return ProviderOperationResult(True, "connected", self.provider, account_id, detail=diagnostics)

    def refresh_token(self, account_id: int) -> ProviderOperationResult:
        account = self.db.get_account_by_id(account_id)
        ok = bool(account and account.get("refresh_token"))
        return ProviderOperationResult(ok, "credential_present" if ok else "credential_required", self.provider, account_id)

    def sync(self, account_id: int, max_results: int = 50, sync_id: int = None) -> ProviderOperationResult:
        if not self.capabilities.supports_imap:
            return ProviderOperationResult(False, "sync_not_supported", self.provider, account_id, "Provider does not expose inbox sync capabilities")
        processed = sync_imap_account(account_id, max_results, sync_id)
        diagnostic = self.db.get_latest_provider_diagnostic(account_id) or {}
        detail = {"processed": processed, "diagnostic": diagnostic}
        return ProviderOperationResult(True, "synced", self.provider, account_id, detail=detail)

    def watch(self, account_id: int) -> ProviderOperationResult:
        return ProviderOperationResult(False, "polling_required", self.provider, account_id, "IMAP providers use scheduled polling in this runtime.")

    def reconnect(self, account_id: int, **kwargs) -> ProviderOperationResult:
        if not kwargs.get("password"):
            self.db.update_account_status(account_id, "needs_reconnect", "credential_required", "Current mailbox credential is required")
            return ProviderOperationResult(False, "credential_required", self.provider, account_id)
        account = self.db.get_account_by_id(account_id)
        diagnostics = IMAPAccountManager(self.db).validate(email=account["email"], password=kwargs["password"], provider=self.provider, host=kwargs.get("host"), port=kwargs.get("port"), security=kwargs.get("security"))
        if diagnostics.get("ok"):
            IMAPAccountManager(self.db).store_account(self.provider, account["email"], kwargs["password"], diagnostics.get("metadata"))
            return ProviderOperationResult(True, "reconnected", self.provider, account_id, detail=diagnostics)
        return ProviderOperationResult(False, diagnostics.get("status", "reconnect_failed"), self.provider, account_id, detail=diagnostics)

    def health_check(self, account_id: int) -> ProviderOperationResult:
        health = MailboxHealthEngine(self.db).account_health(account_id)
        return ProviderOperationResult(bool(health.get("ok")), health.get("status", "unknown"), self.provider, account_id, detail=health)

    def recover(self, account_id: int) -> ProviderOperationResult:
        result = MailboxRecoveryEngine(self.db).recover(account_id)
        return ProviderOperationResult(bool(result.get("ok")), result.get("status", "recovery_failed"), self.provider, account_id, detail=result)

    def disconnect(self, account_id: int) -> ProviderOperationResult:
        self.db.update_account_status(account_id, "paused", "disconnected")
        return ProviderOperationResult(True, "disconnected", self.provider, account_id)


class SMTPProviderAdapter(IMAPProviderAdapter):
    def sync(self, account_id: int, max_results: int = 50, sync_id: int = None) -> ProviderOperationResult:
        if sync_id:
            self.db.update_sync_status(sync_id, "failed", error="SMTP is send-only and cannot sync inbox mail")
        self.db.update_account_status(account_id, "degraded", "sync_not_supported", "SMTP is send-only and cannot sync inbox mail")
        return ProviderOperationResult(False, "sync_not_supported", self.provider, account_id, "SMTP is send-only and cannot sync inbox mail")


class MailboxOrchestrator:
    def __init__(self, db: Database = None):
        self.db = db or Database(config.DB_PATH)
        self.registry = ProviderCapabilityRegistry()
        self.leases = MailboxConnectionManager(self.db)
        self.quarantine = MailboxQuarantineEngine(self.db)

    def adapter_for(self, provider: str) -> ProviderAdapterBase:
        provider = ProviderCapabilityRegistry.normalize(provider)
        if provider == "gmail":
            return GmailProviderAdapter(provider, self.db, self.registry)
        if provider in {"outlook", "microsoft365", "exchange"}:
            return OutlookProviderAdapter(provider, self.db, self.registry)
        if provider == "smtp":
            return SMTPProviderAdapter(provider, self.db, self.registry)
        return IMAPProviderAdapter(provider, self.db, self.registry)

    def adapter_for_account(self, account: Dict) -> ProviderAdapterBase:
        """Choose the runtime adapter from account metadata.

        OAuth-capable providers can still be connected through app-password/IMAP
        when the user explicitly selects that method. In that case the provider
        remains visible as Gmail/Outlook/etc. but sync uses the IMAP adapter.
        """
        try:
            import json
            metadata = json.loads(account.get("metadata") or "{}")
        except Exception:
            metadata = {}
        method = str(metadata.get("connection_method") or "").lower()
        provider = ProviderCapabilityRegistry.normalize(account.get("provider"))
        if method in {"app_password", "imap", "imap_smtp", "advanced_imap", "manual", "password"}:
            return IMAPProviderAdapter("imap", self.db, self.registry)
        return self.adapter_for(provider)

    def validate_account(self, account_id: int, operation: str = "sync") -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing", "message": "Account not found"}
        if account.get("status") == "paused":
            return {"ok": False, "status": "paused", "message": "Account is paused"}
        if self.quarantine.is_quarantined(account_id):
            return {"ok": False, "status": "quarantined", "message": "Account is quarantined"}
        cap = self.registry.get(account.get("provider"))
        try:
            import json
            metadata = json.loads(account.get("metadata") or "{}")
        except Exception:
            metadata = {}
        manual_method = str(metadata.get("connection_method") or "").lower() in {"app_password", "imap", "imap_smtp", "advanced_imap", "manual", "password"}
        if operation == "sync" and not manual_method and not (cap.supports_imap or cap.supports_graph or cap.provider == "gmail"):
            return {"ok": False, "status": "sync_not_supported", "message": "Provider cannot sync inbox mail"}
        if operation == "sync":
            token_health = ProviderTokenManager(self.db).token_health(account_id)
            if not token_health.get("ok") and token_health.get("status") not in {"refresh_recommended"}:
                return {"ok": False, "status": token_health.get("status") or "auth_required", "message": token_health.get("reason") or "Mailbox authentication is not ready", "auth": token_health}
        return {"ok": True, "status": "ok", "account": account, "capabilities": cap.as_dict()}

    def sync_account(self, account_id: int, max_results: int = 50, sync_id: int = None) -> Dict:
        validation = self.validate_account(account_id, "sync")
        if not validation.get("ok"):
            if sync_id:
                self.db.update_sync_status(sync_id, "failed", error=validation.get("message") or validation.get("status"))
            return validation
        account = validation["account"]
        provider = account["provider"]
        with self.leases.account_lease(account_id, provider, "sync") as lease:
            if not lease.get("ok"):
                if sync_id:
                    self.db.update_sync_status(sync_id, "failed", error="Duplicate sync already running")
                return {"ok": False, "status": "duplicate_sync_blocked", "lease": lease}
            adapter = self.adapter_for_account(account)
            try:
                structure = ProviderMailboxTaxonomy(self.db).sync_mailbox_structure(account_id)
                result = adapter.sync(account_id, max_results=max_results, sync_id=sync_id)
                detail = result.detail if isinstance(result.detail, dict) else {"detail": result.detail}
                detail["structure_sync"] = structure
                result.detail = detail
                self.db.add_provider_diagnostic(account_id, provider, result.status, result.as_dict())
                return result.as_dict()
            except Exception as exc:
                logger.exception("Mailbox sync failed for account %s", account_id)
                self.db.update_account_status(account_id, "degraded", "sync_failed", str(exc))
                if sync_id:
                    self.db.update_sync_status(sync_id, "failed", error=str(exc))
                self.db.add_provider_diagnostic(account_id, provider, "sync_failed", {"error": str(exc)})
                return {"ok": False, "status": "sync_failed", "message": str(exc), "account_id": account_id, "provider": provider}

    def connect(self, provider: str, **kwargs) -> Dict:
        adapter = self.adapter_for(provider)
        result = adapter.connect(**kwargs)
        payload = result.as_dict()
        if result.ok and result.account_id:
            try:
                payload["structure_sync"] = ProviderMailboxTaxonomy(self.db).sync_mailbox_structure(result.account_id)
            except Exception as exc:
                payload["structure_sync"] = {"ok": False, "message": str(exc)}
        return payload

    def reconnect(self, account_id: int, **kwargs) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        with self.leases.account_lease(account_id, account["provider"], "reconnect") as lease:
            if not lease.get("ok"):
                return {"ok": False, "status": "reconnect_already_running", "lease": lease}
            result = self.adapter_for(account["provider"]).reconnect(account_id, **kwargs)
            self.db.add_provider_diagnostic(account_id, account["provider"], result.status, result.as_dict())
            return result.as_dict()

    def health(self, account_id: int = None) -> Dict:
        if account_id:
            account = self.db.get_account_by_id(account_id)
            if not account:
                return {"ok": False, "status": "missing"}
            return self.adapter_for(account["provider"]).health_check(account_id).as_dict()
        return {"accounts": MailboxHealthEngine(self.db).all_health(), "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z"}
