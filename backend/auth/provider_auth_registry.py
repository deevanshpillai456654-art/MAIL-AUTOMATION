"""Provider authentication registry."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Dict, List
from backend.core.provider_capability_registry import ProviderCapabilityRegistry


@dataclass(frozen=True)
class ProviderAuthDefinition:
    provider: str
    auth_type: str
    interactive: bool
    token_refresh: bool
    credential_fields: List[str]
    recovery_modes: List[str]

    def as_dict(self):
        return asdict(self)


class ProviderAuthRegistry:
    def __init__(self, capabilities: ProviderCapabilityRegistry = None):
        self.capabilities = capabilities or ProviderCapabilityRegistry()

    def get(self, provider: str) -> ProviderAuthDefinition:
        cap = self.capabilities.get(provider)
        if cap.supports_oauth and not cap.supports_imap:
            return ProviderAuthDefinition(cap.provider, cap.auth_type, True, True, ["client_id", "client_secret", "redirect_uri"], ["refresh", "consent", "reconnect"])
        if cap.supports_oauth and cap.supports_imap:
            return ProviderAuthDefinition(cap.provider, cap.auth_type, True, cap.supports_refresh, ["client_id", "client_secret", "host", "port"], ["refresh", "credential_update", "reconnect"])
        fields = ["email", "password"]
        if cap.requires_host:
            fields.extend(["host", "port", "security"])
        return ProviderAuthDefinition(cap.provider, cap.auth_type, False, False, fields, ["credential_update", "quarantine"])

    def list(self) -> List[Dict]:
        return [self.get(item["provider"]).as_dict() for item in self.capabilities.list()]
