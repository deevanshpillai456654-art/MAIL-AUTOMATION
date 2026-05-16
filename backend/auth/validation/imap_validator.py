"""Manual IMAP/SMTP/app-password validation.

Only this validator may require mailbox credentials. It is never used for OAuth
strategies.
"""
from __future__ import annotations

from typing import Any, Dict

from .schema_registry import AuthValidationResult


class IMAPPayloadValidator:
    def validate(self, payload: Dict[str, Any], strategy: Any) -> AuthValidationResult:
        password = payload.get("password") or payload.get("app_password")
        errors: Dict[str, str] = {}
        if not password:
            errors["password"] = "Manual IMAP/App Password authentication requires a mailbox credential."
        defaults = getattr(strategy, "defaults", {}) or {}
        host = payload.get("imap_host") or payload.get("host") or defaults.get("imap_host")
        smtp_host = payload.get("smtp_host") or defaults.get("smtp_host")
        if getattr(strategy, "imap_required", True) and not host:
            errors["imap_host"] = "IMAP host is required for manual authentication."
        if getattr(strategy, "smtp_required", False) and not smtp_host:
            errors["smtp_host"] = "SMTP host is required for sending mail."
        ok = not errors
        status = "manual_credentials_present" if ok else ("credential_required" if "password" in errors else "server_settings_required")
        return AuthValidationResult(
            ok=ok,
            status=status,
            auth_type=getattr(strategy, "connection_method", "imap"),
            provider=getattr(strategy, "provider", payload.get("provider", "custom")),
            password_required=True,
            app_password_required=bool(getattr(strategy, "app_password_required", False)),
            imap_required=bool(getattr(strategy, "imap_required", True)),
            smtp_required=bool(getattr(strategy, "smtp_required", False)),
            validate_oauth_tokens_only=False,
            message="Manual credentials are ready for connection testing." if ok else "Manual account setup needs the highlighted fields.",
            errors=errors,
            strategy=strategy.as_dict() if hasattr(strategy, "as_dict") else dict(strategy or {}),
        )
