"""Single provider-aware account validation facade."""
from __future__ import annotations

from typing import Any, Dict

from .oauth_validator import OAuthPayloadValidator
from .imap_validator import IMAPPayloadValidator
from .schema_registry import normalize_auth_method


class ProviderAuthValidator:
    """Dispatch to exactly one validation strategy.

    The dispatch rule is intentionally strict: when the resolved strategy is
    OAuth, no IMAP/SMTP/password validator can run. This prevents the historical
    `Account save failed` conflict where legacy validators executed after OAuth.
    """

    def __init__(self) -> None:
        self.oauth = OAuthPayloadValidator()
        self.imap = IMAPPayloadValidator()

    def validate(self, payload: Dict[str, Any], strategy: Any) -> Dict[str, Any]:
        connection_method = normalize_auth_method(
            getattr(strategy, "connection_method", None) or payload.get("connection_method") or payload.get("auth_method")
        )
        if connection_method == "oauth" or bool(getattr(strategy, "validate_oauth_tokens_only", False)):
            return self.oauth.validate(payload, strategy).as_dict()
        return self.imap.validate(payload, strategy).as_dict()
