"""RequestContext — collects all per-request context into a single object."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .tenant_context import TenantContext
from .user_context   import UserContext


@dataclass
class RequestContext:
    trace_id:  str
    tenant:    Optional[TenantContext] = None
    user:      Optional[UserContext]   = None
    metadata:  Dict[str, Any]          = field(default_factory=dict)

    @property
    def tenant_id(self) -> str:
        return self.tenant.tenant_id if self.tenant else "__system__"

    @property
    def user_id(self) -> Optional[str]:
        return self.user.user_id if self.user else None


_request_ctx: ContextVar[Optional[RequestContext]] = ContextVar("request_ctx", default=None)


def set_request_context(ctx: RequestContext) -> None:
    _request_ctx.set(ctx)


def get_request_context() -> Optional[RequestContext]:
    return _request_ctx.get()
