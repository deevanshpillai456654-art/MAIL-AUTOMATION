"""Microsoft OAuth2 provider (Azure AD / Entra)."""
from __future__ import annotations

from backend import config
from backend.auth.providers.base import BaseOAuthProvider


class MicrosoftOAuthProvider(BaseOAuthProvider):
    AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    PROFILE_URL = "https://graph.microsoft.com/v1.0/me"
    PROVIDER = "outlook"

    def __init__(self, db=None, redirect_uri: str = None,
                 client_id: str = None, client_secret: str = None,
                 tenant_id: str = None, email_address: str = None):
        from backend.auth.provider_config import ProviderConfigManager
        _cfg = ProviderConfigManager().get_oauth_config("microsoft", runtime_redirect_uri=redirect_uri, email_address=email_address)
        self.oauth_config_provider = _cfg.get("oauth_config_provider") or "microsoft"
        self.oauth_config_email = _cfg.get("oauth_config_email")
        self.tenant_id = tenant_id or _cfg.get("tenant_id") or config.OUTLOOK_TENANT_ID or "common"
        super().__init__(
            db=db,
            redirect_uri=redirect_uri or _cfg.get("redirect_uri") or config.OUTLOOK_REDIRECT_URI,
            client_id=client_id or _cfg.get("client_id") or config.OUTLOOK_CLIENT_ID or "",
            client_secret=client_secret or _cfg.get("client_secret") or config.OUTLOOK_CLIENT_SECRET or "",
        )

    def _scopes(self) -> list[str]:
        return [
            "offline_access",
            "User.Read",
            "Mail.Read",
            "Mail.ReadWrite",
            "Mail.Send",
            "MailboxSettings.ReadWrite",
        ]

    def _build_auth_url(self, state, redirect_uri, code_challenge, login_hint=None):
        from urllib.parse import urlencode
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": " ".join(self._scopes()),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
        return f"{self.AUTH_URL.format(tenant=self.tenant_id)}?{urlencode(params)}"

    def _token_url(self) -> str:
        return self.TOKEN_URL.format(tenant=self.tenant_id)

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str = None):
        import requests
        import logging
        from backend import config as cfg
        logger = logging.getLogger(__name__)
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(self._scopes()),
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
                    "expires_in": tok.get("expires_in", cfg.TOKEN_EXPIRY_SECONDS),
                }
            logger.warning("microsoft token exchange failed %s: %s", resp.status_code, resp.text[:300])
        except requests.RequestException as exc:
            logger.exception("microsoft token exchange error: %s", exc)
        return None
