"""Centralized auth validation pipeline for provider onboarding.

This package is the single validation entry point for OAuth, IMAP, SMTP and
app-password account onboarding. OAuth validation never inspects mailbox
password fields.
"""
from .provider_validator import ProviderAuthValidator
from .schema_registry import AuthValidationResult, normalize_auth_method

__all__ = ["ProviderAuthValidator", "AuthValidationResult", "normalize_auth_method"]
