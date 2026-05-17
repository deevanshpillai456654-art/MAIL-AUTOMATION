"""UserContext — immutable per-request user state carrier."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class UserContext:
    user_id:   str
    email:     str       = ""
    name:      str       = ""
    roles:     tuple     = ()
    tenant_id: str       = "__system__"

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def is_admin(self) -> bool:
        return "admin" in self.roles or "superadmin" in self.roles


_user_ctx: ContextVar[Optional[UserContext]] = ContextVar("user_ctx", default=None)


def set_user_context(ctx: UserContext) -> None:
    _user_ctx.set(ctx)


def get_user_context() -> Optional[UserContext]:
    return _user_ctx.get()
