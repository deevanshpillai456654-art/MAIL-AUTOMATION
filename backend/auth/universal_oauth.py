"""Data-driven OAuth helper for non-Google/Microsoft providers.

Gmail and Microsoft keep their specialized handlers because they have mature API
clients in this codebase. This helper gives Yahoo/Zoho and future OAuth-capable
providers the same production onboarding guarantees: PKCE, state persistence,
secure token storage, refresh support, and zero password requirements.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import urlencode

import requests

from backend import config
from backend.auth.provider_config import OAUTH_GROUPS, ProviderConfigManager, normalize_provider
from backend.auth.token_crypto import TokenCipher
from backend.db.database import Database

logger = logging.getLogger(__name__)


class UniversalOAuth:
    def __init__(self, provider: str, db: Database = None, redirect_uri: str = None, cipher: TokenCipher = None):
        self.provider = normalize_provider(provider)
        if self.provider not in OAUTH_GROUPS:
            raise ValueError(f"Provider {provider!r} is not OAuth-capable")
        self.meta = OAUTH_GROUPS[self.provider]
        saved = ProviderConfigManager().get_oauth_config(self.provider, runtime_redirect_uri=redirect_uri)
        self.client_id = saved.get("client_id")
        self.client_secret = saved.get("client_secret")
        self.redirect_uri = redirect_uri or saved.get("redirect_uri")
        self.tenant_id = saved.get("tenant_id") or "common"
        self.scopes = saved.get("scopes") or self.meta.get("scopes", [])
        self.db = db or Database(config.DB_PATH)
        self.cipher = cipher or TokenCipher()

    @staticmethod
    def generate_state() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_pkce_pair() -> Dict[str, str]:
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return {"verifier": verifier, "challenge": challenge}

    def validate_configuration(self) -> Dict:
        missing = []
        if not self.client_id or str(self.client_id).startswith(("YOUR_", "your_")):
            missing.append(self.meta["client_id_env"])
        if not self.client_secret or str(self.client_secret).startswith(("YOUR_", "your_")):
            missing.append(self.meta["client_secret_env"])
        return {"configured": not missing, "missing": missing, "provider": self.provider}

    def _format_url(self, template: str) -> str:
        return template.format(tenant=self.tenant_id)

    def create_authorization_request(self, redirect_uri: str = None, login_hint: str = None) -> Dict:
        config_status = self.validate_configuration()
        if not config_status["configured"]:
            return {
                "configured": False,
                "provider": self.provider,
                "missing": config_status["missing"],
                "message": f"{self.meta['display_name']} OAuth credentials are not configured.",
                "password_required": False,
            }
        state = self.generate_state()
        pkce = self.generate_pkce_pair()
        callback = redirect_uri or self.redirect_uri
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        self.db.create_oauth_state(self.provider, state, pkce["verifier"], callback, expires_at)
        return {
            "configured": True,
            "provider": self.provider,
            "state": state,
            "auth_url": self.get_authorization_url(state=state, redirect_uri=callback, code_challenge=pkce["challenge"], login_hint=login_hint),
            "expires_at": expires_at,
            "password_required": False,
        }

    def get_authorization_url(self, state: str, redirect_uri: str = None, code_challenge: str = None, login_hint: str = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "state": state,
        }
        if self.provider == "zoho":
            params["access_type"] = "offline"
            params["prompt"] = "consent"
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self._format_url(self.meta['auth_url'])}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str, redirect_uri: str = None, code_verifier: str = None) -> Optional[Dict]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or self.redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        try:
            response = requests.post(self._format_url(self.meta["token_url"]), data=data, timeout=20)
            if response.ok:
                token_data = response.json()
                return {
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": token_data.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                    "scope": token_data.get("scope"),
                }
            logger.warning("%s token exchange failed: %s %s", self.provider, response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("%s token exchange error: %s", self.provider, exc)
        return None

    def refresh_access_token(self, refresh_token: str) -> Optional[Dict]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        try:
            response = requests.post(self._format_url(self.meta["token_url"]), data=data, timeout=20)
            if response.ok:
                token_data = response.json()
                return {
                    "access_token": token_data["access_token"],
                    "expires_in": token_data.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                    "scope": token_data.get("scope"),
                }
            logger.warning("%s token refresh failed: %s %s", self.provider, response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("%s token refresh error: %s", self.provider, exc)
        return None

    def get_user_profile(self, access_token: str) -> Optional[Dict]:
        profile_url = self.meta.get("profile_url")
        if not profile_url:
            return None
        try:
            response = requests.get(self._format_url(profile_url), headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
            if response.ok:
                return response.json()
            logger.warning("%s profile lookup failed: %s %s", self.provider, response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("%s profile lookup error: %s", self.provider, exc)
        return None

    def store_account(self, account_id: int, access_token: str, refresh_token: str = None, expires_in: int = None):
        encrypted_access = self.cipher.encrypt(access_token)
        encrypted_refresh = self.cipher.encrypt(refresh_token) if refresh_token else None
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in or config.TOKEN_EXPIRY_SECONDS)).isoformat()
        self.db.update_account_tokens(account_id, encrypted_access, encrypted_refresh, expires_at)

    def get_valid_token(self, account_id: int) -> Optional[str]:
        account = self.db.get_account_by_id(account_id)
        if not account or not account.get("access_token"):
            return None
        raw_expiry = account.get("token_expiry")
        expires_at = None
        if raw_expiry:
            dt = datetime.fromisoformat(raw_expiry)
            expires_at = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        if expires_at and expires_at > datetime.now(timezone.utc):
            return self.cipher.decrypt(account["access_token"])
        if account.get("refresh_token"):
            decrypted_refresh = self.cipher.decrypt(account["refresh_token"])
            new_token = self.refresh_access_token(decrypted_refresh)
            if new_token:
                self.store_account(account_id, new_token["access_token"], None, new_token["expires_in"])
                return new_token["access_token"]
        self.db.update_account_status(account_id, "needs_reconnect", "token_refresh_failed", f"Unable to refresh {self.provider} token")
        return None
