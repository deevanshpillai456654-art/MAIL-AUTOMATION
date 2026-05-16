"""OAuth-only validation.

This module intentionally ignores password/app-password/IMAP/SMTP fields.
"""
from __future__ import annotations

from typing import Any, Dict

from .schema_registry import AuthValidationResult


class OAuthPayloadValidator:
    def validate(self, payload: Dict[str, Any], strategy: Any) -> AuthValidationResult:
        configured = bool(getattr(strategy, "configured", False))
        status = "oauth_ready" if configured else "provider_setup_required"
        return AuthValidationResult(
            ok=configured,
            status=status,
            auth_type="oauth",
            provider=getattr(strategy, "provider", payload.get("provider", "unknown")),
            password_required=False,
            app_password_required=False,
            imap_required=False,
            smtp_required=False,
            validate_oauth_tokens_only=True,
            message=(
                "OAuth provider is ready. Continue with provider sign-in; mailbox passwords are not accepted."
                if configured else
                "OAuth provider configuration is required before sign-in. Password validation remains disabled."
            ),
            errors={},
            strategy=strategy.as_dict() if hasattr(strategy, "as_dict") else dict(strategy or {}),
        )
