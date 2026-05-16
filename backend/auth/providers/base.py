"""Base OAuth provider — shared PKCE + token exchange contract."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import urlencode

import requests

from backend import config
from backend.auth.pkce import generate_pkce_pair, generate_state
from backend.auth.state_store import OAuthStateStore
from backend.auth.token_store import TokenStore
from backend.db.database import Database

logger = logging.getLogger(__name__)


class BaseOAuthProvider:
    AUTH_URL: str = ""
    TOKEN_URL: str = ""
    PROFILE_URL: str = ""
    PROVIDER: str = ""

    def __init__(self, db: Database = None, redirect_uri: str = None,
                 client_id: str = None, client_secret: str = None):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.redirect_uri = redirect_uri or ""
        self._db = db or Database(config.DB_PATH)
        self._state_store = OAuthStateStore(self._db)
        self._token_store = TokenStore(self._db)

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret
                    and not self.client_id.startswith(("YOUR_", "your_"))
                    and not self.client_secret.startswith(("YOUR_", "your_")))

    def create_authorization_request(self, redirect_uri: str = None,
                                     login_hint: str = None) -> Dict:
        if not self.is_configured():
            return {
                "configured": False,
                "provider": self.PROVIDER,
                "missing": self._missing_credentials(),
                "message": f"{self.PROVIDER.title()} OAuth credentials are not configured.",
                "password_required": False,
            }
        state = generate_state()
        pkce = generate_pkce_pair()
        callback = redirect_uri or self.redirect_uri
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        self._state_store.create(self.PROVIDER, state, pkce["verifier"], callback, expires_at)
        return {
            "configured": True,
            "provider": self.PROVIDER,
            "state": state,
            "auth_url": self._build_auth_url(state, callback, pkce["challenge"], login_hint),
            "expires_at": expires_at,
            "password_required": False,
        }

    def _build_auth_url(self, state: str, redirect_uri: str,
                        code_challenge: str, login_hint: str = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes()),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def _scopes(self) -> list[str]:
        return []

    def _missing_credentials(self) -> list[str]:
        missing = []
        if not self.client_id or self.client_id.startswith(("YOUR_", "your_")):
            missing.append(f"{self.PROVIDER.upper()}_CLIENT_ID")
        if not self.client_secret or self.client_secret.startswith(("YOUR_", "your_")):
            missing.append(f"{self.PROVIDER.upper()}_CLIENT_SECRET")
        return missing

    def exchange_code(self, code: str, redirect_uri: str,
                      code_verifier: str = None) -> Optional[Dict]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        try:
            resp = requests.post(self._token_url(), data=data, timeout=20)
            if resp.ok:
                tok = resp.json()
                return {
                    "access_token": tok["access_token"],
                    "refresh_token": tok.get("refresh_token"),
                    "expires_in": tok.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                }
            logger.warning("%s token exchange failed %s: %s", self.PROVIDER, resp.status_code, resp.text[:300])
        except requests.RequestException as exc:
            logger.exception("%s token exchange error: %s", self.PROVIDER, exc)
        return None

    def refresh_token(self, refresh_tok: str) -> Optional[Dict]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_tok,
            "grant_type": "refresh_token",
        }
        try:
            resp = requests.post(self._token_url(), data=data, timeout=20)
            if resp.ok:
                tok = resp.json()
                return {
                    "access_token": tok["access_token"],
                    "expires_in": tok.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                }
            logger.warning("%s token refresh failed %s: %s", self.PROVIDER, resp.status_code, resp.text[:300])
        except requests.RequestException as exc:
            logger.exception("%s token refresh error: %s", self.PROVIDER, exc)
        return None

    def get_profile(self, access_token: str) -> Optional[Dict]:
        if not self.PROFILE_URL:
            return None
        try:
            resp = requests.get(
                self.PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            if resp.ok:
                return resp.json()
            logger.warning("%s profile fetch failed %s", self.PROVIDER, resp.status_code)
        except requests.RequestException as exc:
            logger.exception("%s profile fetch error: %s", self.PROVIDER, exc)
        return None

    def _token_url(self) -> str:
        return self.TOKEN_URL
