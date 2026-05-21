"""Provider adapter interface used by the mailbox orchestrator."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from backend.db.database import Database
from backend.core.provider_capability_registry import ProviderCapabilityRegistry


@dataclass
class ProviderOperationResult:
    ok: bool
    status: str
    provider: str
    account_id: Optional[int] = None
    message: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "provider": self.provider,
            "account_id": self.account_id,
            "message": self.message,
            "detail": self.detail,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


class ProviderAdapterBase(ABC):
    def __init__(self, provider: str, db: Database, registry: ProviderCapabilityRegistry = None):
        self.provider = ProviderCapabilityRegistry.normalize(provider)
        self.db = db
        self.registry = registry or ProviderCapabilityRegistry()
        self.capabilities = self.registry.get(self.provider)

    @abstractmethod
    def connect(self, account_id: int = None, **kwargs) -> ProviderOperationResult: ...

    @abstractmethod
    def refresh_token(self, account_id: int) -> ProviderOperationResult: ...

    @abstractmethod
    def sync(self, account_id: int, max_results: int = 50, sync_id: int = None) -> ProviderOperationResult: ...

    @abstractmethod
    def watch(self, account_id: int) -> ProviderOperationResult: ...

    @abstractmethod
    def reconnect(self, account_id: int, **kwargs) -> ProviderOperationResult: ...

    @abstractmethod
    def health_check(self, account_id: int) -> ProviderOperationResult: ...

    @abstractmethod
    def recover(self, account_id: int) -> ProviderOperationResult: ...

    @abstractmethod
    def disconnect(self, account_id: int) -> ProviderOperationResult: ...

    def validate_capabilities(self) -> ProviderOperationResult:
        return ProviderOperationResult(
            ok=True,
            status="capabilities_validated",
            provider=self.provider,
            detail=self.capabilities.as_dict(),
        )
