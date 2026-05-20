"""OAuth lifecycle automation for supported providers."""
from __future__ import annotations
from typing import Dict
from backend.db.database import Database
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.auth.gmail_auth import GmailOAuth
from backend.auth.outlook_auth import OutlookOAuth
from backend.auth.provider_token_manager import ProviderTokenManager


class OAuthLifecycleManager:
    def __init__(self, db: Database):
        self.db = db
        self.tokens = ProviderTokenManager(db)
        self.registry = ProviderCapabilityRegistry()

    def client_for(self, provider: str, redirect_uri: str = None, email_address: str = None):
        provider = ProviderCapabilityRegistry.normalize(provider)
        if provider == "gmail":
            return GmailOAuth(db=self.db, redirect_uri=redirect_uri, email_address=email_address)
        if provider in ("outlook", "microsoft365", "exchange"):
            return OutlookOAuth(db=self.db, redirect_uri=redirect_uri, email_address=email_address)
        raise ValueError(f"Provider {provider} does not support OAuth in this runtime")

    def start(self, provider: str, redirect_uri: str, email_address: str = None) -> Dict:
        client = self.client_for(provider, redirect_uri, email_address=email_address)
        result = client.create_authorization_request(redirect_uri=redirect_uri, login_hint=email_address)
        result["auth_lifecycle"] = "started" if result.get("configured") else "configuration_required"
        return result

    def refresh_if_needed(self, account_id: int) -> Dict:
        health = self.tokens.token_health(account_id)
        if health.get("status") in ("expired", "refresh_recommended"):
            token = self.tokens.get_valid_access_token(account_id)
            return {"status": "refreshed" if token else "needs_reconnect", "ok": bool(token), "health": health}
        return {"status": health.get("status"), "ok": health.get("ok", False), "health": health}
