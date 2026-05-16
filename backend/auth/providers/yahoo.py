"""Yahoo OAuth2 provider."""
from __future__ import annotations

from backend import config
from backend.auth.providers.base import BaseOAuthProvider


class YahooOAuthProvider(BaseOAuthProvider):
    AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
    TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
    PROFILE_URL = "https://api.login.yahoo.com/openid/v1/userinfo"
    PROVIDER = "yahoo"

    def __init__(self, db=None, redirect_uri: str = None,
                 client_id: str = None, client_secret: str = None):
        from backend.auth.provider_config import ProviderConfigManager
        _cfg = ProviderConfigManager().get_oauth_config("yahoo", runtime_redirect_uri=redirect_uri)
        super().__init__(
            db=db,
            redirect_uri=redirect_uri or _cfg.get("redirect_uri") or config.YAHOO_REDIRECT_URI,
            client_id=client_id or _cfg.get("client_id") or "",
            client_secret=client_secret or _cfg.get("client_secret") or "",
        )

    def _scopes(self) -> list[str]:
        return ["openid", "mail-r", "mail-w"]
