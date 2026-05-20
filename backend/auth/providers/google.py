"""Google OAuth2 provider."""
from __future__ import annotations

from backend import config
from backend.auth.providers.base import BaseOAuthProvider


class GoogleOAuthProvider(BaseOAuthProvider):
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    PROFILE_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
    PROVIDER = "gmail"

    def __init__(self, db=None, redirect_uri: str = None,
                 client_id: str = None, client_secret: str = None,
                 email_address: str = None):
        from backend.auth.provider_config import ProviderConfigManager
        _cfg = ProviderConfigManager().get_oauth_config("gmail", runtime_redirect_uri=redirect_uri, email_address=email_address)
        self.oauth_config_provider = _cfg.get("oauth_config_provider") or "gmail"
        self.oauth_config_email = _cfg.get("oauth_config_email")
        super().__init__(
            db=db,
            redirect_uri=redirect_uri or _cfg.get("redirect_uri") or config.GMAIL_REDIRECT_URI,
            client_id=client_id or _cfg.get("client_id") or config.GMAIL_CLIENT_ID or "",
            client_secret=client_secret or _cfg.get("client_secret") or config.GMAIL_CLIENT_SECRET or "",
        )

    def _scopes(self) -> list[str]:
        return [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.labels",
            "https://www.googleapis.com/auth/gmail.send",
        ]

    def _build_auth_url(self, state, redirect_uri, code_challenge, login_hint=None):
        from urllib.parse import urlencode
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(self._scopes()),
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "false",
            "max_age": "0",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"
