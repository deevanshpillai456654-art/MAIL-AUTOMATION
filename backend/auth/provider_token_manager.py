"""Provider token governance with encrypted storage and scoped refresh."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
import logging

from backend import config
from backend.auth.token_crypto import TokenCipher
from backend.auth.gmail_auth import GmailOAuth
from backend.auth.outlook_auth import OutlookOAuth
from backend.auth.universal_oauth import UniversalOAuth
from backend.auth.provider_config import oauth_group_for
from backend.db.database import Database
from backend.core.provider_capability_registry import ProviderCapabilityRegistry

logger = logging.getLogger(__name__)


class ProviderTokenManager:
    def __init__(self, db: Database = None, cipher: TokenCipher = None):
        self.db = db or Database(config.DB_PATH)
        self.cipher = cipher or TokenCipher()
        self.registry = ProviderCapabilityRegistry()

    def _oauth_client(self, provider: str):
        provider = ProviderCapabilityRegistry.normalize(provider)
        if provider == "gmail":
            return GmailOAuth(db=self.db, cipher=self.cipher)
        if provider in ("outlook", "microsoft365", "exchange"):
            return OutlookOAuth(db=self.db, cipher=self.cipher)
        group = oauth_group_for(provider)
        if group in {"yahoo", "zoho", "yandex"}:
            try:
                return UniversalOAuth(provider=group, db=self.db, cipher=self.cipher)
            except ValueError:
                return None
        return None

    @staticmethod
    def _expiry(value: Optional[str]) -> Optional[datetime]:
        try:
            if not value:
                return None
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (TypeError, ValueError):
            return None

    def token_health(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing", "reason": "account_not_found"}
        provider = account.get("provider")
        cap = self.registry.get(provider)
        expires_at = self._expiry(account.get("token_expiry"))
        now = datetime.now(timezone.utc)
        encrypted = bool(account.get("access_token") or account.get("refresh_token"))
        metadata = {}
        try:
            import json
            metadata = json.loads(account.get("metadata") or "{}")
        except Exception:
            metadata = {}
        manual_method = str(metadata.get("connection_method") or "").lower() in {"app_password", "imap", "imap_smtp", "advanced_imap", "manual", "password"}
        if cap.supports_oauth and not manual_method:
            if not encrypted:
                return {"ok": False, "status": "needs_reconnect", "reason": "missing_oauth_tokens", "provider": provider}
            if expires_at and expires_at <= now:
                return {"ok": False, "status": "expired", "reason": "access_token_expired", "provider": provider}
            if expires_at and expires_at <= now + timedelta(minutes=5):
                return {"ok": True, "status": "refresh_recommended", "provider": provider, "expires_at": account.get("token_expiry")}
        else:
            if cap.supports_imap and not account.get("refresh_token"):
                return {"ok": False, "status": "credential_required", "reason": "missing_encrypted_credential", "provider": provider}
        return {"ok": True, "status": "ok", "provider": provider, "expires_at": account.get("token_expiry"), "encrypted_secret_present": encrypted}

    def get_valid_access_token(self, account_id: int) -> Optional[str]:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return None
        provider = ProviderCapabilityRegistry.normalize(account.get("provider"))
        client = self._oauth_client(provider)
        if not client:
            return None
        token = client.get_valid_token(account_id)
        if token:
            self.db.add_provider_diagnostic(account_id, provider, "token_ok", {"status": "token_ok"})
            return token
        self.db.add_provider_diagnostic(account_id, provider, "token_refresh_failed", {"status": "needs_reconnect"})
        return None

    def store_tokens(self, account_id: int, access_token: str, refresh_token: str = None, expires_in: int = None) -> Dict:
        encrypted_access = self.cipher.encrypt(access_token)
        encrypted_refresh = self.cipher.encrypt(refresh_token) if refresh_token else None
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in or config.TOKEN_EXPIRY_SECONDS)).isoformat()
        self.db.update_account_tokens(account_id, encrypted_access, encrypted_refresh, expires_at)
        return {"status": "stored", "account_id": account_id, "expires_at": expires_at, "refresh_rotated": bool(refresh_token)}

    def revoke_local_tokens(self, account_id: int, reason: str = "revoked") -> Dict:
        self.db.execute("UPDATE accounts SET access_token = NULL, token_expiry = NULL, status = ?, reconnect_state = ?, last_error = ?, updated_at = ? WHERE id = ?", ("needs_reconnect", "token_revoked", reason, datetime.now(timezone.utc).isoformat(), account_id))
        self.db.add_provider_diagnostic(account_id, "unknown", "token_revoked", {"reason": reason})
        return {"status": "revoked", "account_id": account_id, "reason": reason}
