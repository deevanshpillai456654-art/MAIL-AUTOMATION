"""Auth validation schema registry.

Rules are deliberately small and explicit to prevent legacy validators from
executing IMAP/password checks during OAuth onboarding.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

OAUTH_METHODS = {"oauth", "oauth2", "provider_oauth", "google_oauth", "microsoft_oauth"}
MANUAL_METHODS = {"imap", "smtp", "imap_smtp", "manual", "password", "app_password", "exchange"}


def normalize_auth_method(value: Optional[str]) -> str:
    method = (value or "auto").strip().lower().replace("-", "_")
    if method in OAUTH_METHODS:
        return "oauth"
    if method in {"password", "manual", "imap_smtp"}:
        return "imap"
    if method == "smtp":
        return "imap"
    if method == "app_password":
        return "app_password"
    if method == "exchange":
        return "exchange"
    return method or "auto"


@dataclass(frozen=True)
class AuthValidationResult:
    ok: bool
    status: str
    auth_type: str
    provider: str
    password_required: bool
    app_password_required: bool
    imap_required: bool
    smtp_required: bool
    validate_oauth_tokens_only: bool
    message: str
    errors: Dict[str, str]
    strategy: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)
