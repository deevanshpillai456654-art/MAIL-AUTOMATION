"""OAuth provider configuration registry.

Thin facade over ProviderConfigManager that exposes typed accessors
for the authoritative provider credentials.
"""
from __future__ import annotations

from backend import config
from backend.auth.provider_config import ProviderConfigManager


def redirect_uri_for(provider: str, base_url: str = None) -> str:
    """Return the canonical redirect URI for a provider."""
    mgr = ProviderConfigManager()
    saved = mgr.get_oauth_config(provider)
    if saved.get("redirect_uri"):
        return saved["redirect_uri"]
    port = getattr(config, "API_PORT", 4597)
    slug = {"gmail": "google", "google": "google",
            "outlook": "microsoft", "microsoft": "microsoft",
            "yahoo": "yahoo", "zoho": "zoho"}.get(provider, provider)
    return f"http://127.0.0.1:{port}/api/v1/oauth/{slug}/callback"
