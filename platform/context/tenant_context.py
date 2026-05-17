"""
TenantContext — immutable per-request tenant state carrier.

Populated by TenantMiddleware from the inbound request and threaded
through the call stack via contextvars.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TenantContext:
    tenant_id:   str
    tenant_name: str = ""
    plan:        str = "free"        # free | starter | pro | enterprise
    features:    tuple = ()          # enabled feature flags
    metadata:    Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})

    def has_feature(self, flag: str) -> bool:
        return flag in self.features

    def is_enterprise(self) -> bool:
        return self.plan == "enterprise"


# ContextVar for async propagation
_tenant_ctx: ContextVar[Optional[TenantContext]] = ContextVar("tenant_ctx", default=None)


def set_tenant_context(ctx: TenantContext) -> None:
    _tenant_ctx.set(ctx)


def get_tenant_context() -> Optional[TenantContext]:
    return _tenant_ctx.get()


def require_tenant_context() -> TenantContext:
    ctx = _tenant_ctx.get()
    if ctx is None:
        raise RuntimeError("TenantContext not set for this request")
    return ctx
