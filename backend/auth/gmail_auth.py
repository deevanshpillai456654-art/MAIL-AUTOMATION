"""
Gmail OAuth2 authentication handler.
"""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from urllib.parse import urlencode

import requests

from backend import config
from backend.auth.token_crypto import TokenCipher
from backend.auth.provider_config import ProviderConfigManager
from backend.db.database import Database

logger = logging.getLogger(__name__)


class GmailOAuth:
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

    def __init__(self, db: Database = None, client_id: str = None, client_secret: str = None,
                 redirect_uri: str = None, cipher: TokenCipher = None):
        saved = ProviderConfigManager().get_oauth_config("gmail", runtime_redirect_uri=redirect_uri)
        self.client_id = client_id if client_id is not None else saved.get("client_id") or config.GMAIL_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else saved.get("client_secret") or config.GMAIL_CLIENT_SECRET
        self.redirect_uri = redirect_uri or saved.get("redirect_uri") or config.GMAIL_REDIRECT_URI
        self.scopes = [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.send",
        ]
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
        if not self.client_id or self.client_id.startswith("YOUR_") or self.client_id.startswith("your_"):
            missing.append("GMAIL_CLIENT_ID")
        if not self.client_secret or self.client_secret.startswith("YOUR_") or self.client_secret.startswith("your_"):
            missing.append("GMAIL_CLIENT_SECRET")
        return {
            "configured": not missing,
            "missing": missing,
            "provider": "gmail",
        }

    def create_authorization_request(self, redirect_uri: str = None, login_hint: str = None) -> Dict:
        config_status = self.validate_configuration()
        if not config_status["configured"]:
            return {
                "configured": False,
                "provider": "gmail",
                "missing": config_status["missing"],
                "message": "Gmail OAuth credentials are not configured.",
            }

        state = self.generate_state()
        pkce = self.generate_pkce_pair()
        callback = redirect_uri or self.redirect_uri
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        self.db.create_oauth_state("gmail", state, pkce["verifier"], callback, expires_at)

        return {
            "configured": True,
            "provider": "gmail",
            "state": state,
            "auth_url": self.get_authorization_url(
                state=state,
                redirect_uri=callback,
                code_challenge=pkce["challenge"],
                login_hint=login_hint,
            ),
            "expires_at": expires_at,
        }

    def get_authorization_url(self, state: str, redirect_uri: str = None, code_challenge: str = None, login_hint: str = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        if login_hint:
            params["login_hint"] = login_hint
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str, redirect_uri: str = None,
                                 code_verifier: str = None) -> Optional[Dict]:
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
            response = requests.post(self.TOKEN_URL, data=data, timeout=20)
            if response.ok:
                token_data = response.json()
                return {
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": token_data.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                }
            logger.warning("Gmail token exchange failed: %s %s", response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("Gmail token exchange error: %s", exc)
        return None

    def refresh_access_token(self, refresh_token: str) -> Optional[Dict]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            response = requests.post(self.TOKEN_URL, data=data, timeout=20)
            if response.ok:
                token_data = response.json()
                return {
                    "access_token": token_data["access_token"],
                    "expires_in": token_data.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                }
            logger.warning("Gmail token refresh failed: %s %s", response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("Gmail token refresh error: %s", exc)
        return None

    def get_user_profile(self, access_token: str) -> Optional[Dict]:
        try:
            response = requests.get(
                self.USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            if response.ok:
                return response.json()
            logger.warning("Gmail user profile failed: %s %s", response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("Gmail user profile error: %s", exc)
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

        self.db.update_account_status(account_id, "needs_reconnect", "token_refresh_failed", "Unable to refresh Gmail token")
        return None
