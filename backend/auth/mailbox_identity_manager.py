"""Mailbox identity normalization and isolation helpers."""
from __future__ import annotations
import hashlib
from typing import Dict
from backend.core.provider_capability_registry import ProviderCapabilityRegistry


class MailboxIdentityManager:
    @staticmethod
    def normalize_email(email: str) -> str:
        return (email or "").strip().lower()

    @staticmethod
    def tenant_key(user_id: int) -> str:
        return f"tenant:{int(user_id or 0)}"

    @classmethod
    def mailbox_key(cls, user_id: int, provider: str, email: str) -> str:
        normalized = f"{cls.tenant_key(user_id)}:{ProviderCapabilityRegistry.normalize(provider)}:{cls.normalize_email(email)}"
        return hashlib.sha256(normalized.encode()).hexdigest()

    @classmethod
    def assert_account_scope(cls, account: Dict, expected_user_id: int = None, provider: str = None) -> None:
        if not account:
            raise ValueError("Mailbox account not found")
        if expected_user_id is not None and int(account.get("user_id") or 0) != int(expected_user_id):
            raise PermissionError("Mailbox does not belong to the requested tenant/user scope")
        if provider and ProviderCapabilityRegistry.normalize(account.get("provider")) != ProviderCapabilityRegistry.normalize(provider):
            raise PermissionError("Mailbox provider scope mismatch")
