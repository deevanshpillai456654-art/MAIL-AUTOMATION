"""
Outlook (Microsoft Graph) OAuth2 authentication handler.
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


class OutlookOAuth:
    AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    PROFILE_URL = "https://graph.microsoft.com/v1.0/me"

    def __init__(self, tenant_id: str = None, db: Database = None, client_id: str = None,
                 client_secret: str = None, redirect_uri: str = None, cipher: TokenCipher = None,
                 email_address: str = None):
        saved = ProviderConfigManager().get_oauth_config("microsoft", runtime_redirect_uri=redirect_uri, email_address=email_address)
        self.client_id = client_id if client_id is not None else saved.get("client_id") or config.OUTLOOK_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else saved.get("client_secret") or config.OUTLOOK_CLIENT_SECRET
        self.tenant_id = tenant_id or saved.get("tenant_id") or config.OUTLOOK_TENANT_ID
        self.redirect_uri = redirect_uri or saved.get("redirect_uri") or config.OUTLOOK_REDIRECT_URI
        self.oauth_config_provider = saved.get("oauth_config_provider") or "microsoft"
        self.oauth_config_email = saved.get("oauth_config_email")
        self.scopes = [
            "offline_access",
            "User.Read",
            "Mail.Read",
            "Mail.ReadWrite",
            "Mail.Send",
            "MailboxSettings.ReadWrite",
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
            missing.append("OUTLOOK_CLIENT_ID")
        if not self.client_secret or self.client_secret.startswith("YOUR_") or self.client_secret.startswith("your_"):
            missing.append("OUTLOOK_CLIENT_SECRET")
        return {
            "configured": not missing,
            "missing": missing,
            "provider": "outlook",
        }

    def create_authorization_request(self, redirect_uri: str = None, login_hint: str = None,
                                     oauth_config_provider: str = None,
                                     oauth_config_email: str = None,
                                     redirect_after_callback: str = None) -> Dict:
        config_status = self.validate_configuration()
        if not config_status["configured"]:
            return {
                "configured": False,
                "provider": "outlook",
                "missing": config_status["missing"],
                "message": "Microsoft Graph OAuth credentials are not configured.",
            }

        state = self.generate_state()
        pkce = self.generate_pkce_pair()
        callback = redirect_uri or self.redirect_uri
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        self.db.create_oauth_state(
            "outlook",
            state,
            pkce["verifier"],
            callback,
            expires_at,
            login_hint,
            oauth_config_provider=oauth_config_provider or self.oauth_config_provider,
            oauth_config_email=oauth_config_email if oauth_config_email is not None else self.oauth_config_email,
            redirect_after_callback=redirect_after_callback,
        )

        return {
            "configured": True,
            "provider": "outlook",
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
            "response_mode": "query",
            "scope": " ".join(self.scopes),
            "state": state,
            "prompt": "select_account",
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self.AUTH_URL.format(tenant=self.tenant_id)}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str, redirect_uri: str = None,
                                 code_verifier: str = None) -> Optional[Dict]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or self.redirect_uri,
            "scope": " ".join(self.scopes),
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        try:
            response = requests.post(self.TOKEN_URL.format(tenant=self.tenant_id), data=data, timeout=20)
            if response.ok:
                token_data = response.json()
                return {
                    "access_token": token_data["access_token"],
                    "refresh_token": token_data.get("refresh_token"),
                    "expires_in": token_data.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                }
            logger.warning("Microsoft token exchange failed: %s %s", response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("Microsoft token exchange error: %s", exc)
        return None

    def refresh_access_token(self, refresh_token: str) -> Optional[Dict]:
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(self.scopes),
        }

        try:
            response = requests.post(self.TOKEN_URL.format(tenant=self.tenant_id), data=data, timeout=20)
            if response.ok:
                token_data = response.json()
                return {
                    "access_token": token_data["access_token"],
                    "expires_in": token_data.get("expires_in", config.TOKEN_EXPIRY_SECONDS),
                }
            logger.warning("Microsoft token refresh failed: %s %s", response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("Microsoft token refresh error: %s", exc)
        return None

    def get_user_profile(self, access_token: str) -> Optional[Dict]:
        try:
            response = requests.get(
                self.PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=20,
            )
            if response.ok:
                return response.json()
            logger.warning("Microsoft profile lookup failed: %s %s", response.status_code, response.text[:500])
        except requests.RequestException as exc:
            logger.exception("Microsoft profile lookup error: %s", exc)
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

        self.db.update_account_status(account_id, "needs_reconnect", "token_refresh_failed", "Unable to refresh Outlook token")
        return None
