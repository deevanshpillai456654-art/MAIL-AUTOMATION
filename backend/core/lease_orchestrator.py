"""Mailbox-safe lease orchestration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .lease_manager import LeaseManager


@dataclass(frozen=True)
class MailboxLease:
    lease_id: str
    tenant_id: str
    account_id: str
    owner_id: str


class LeaseOrchestrator:
    def __init__(self, manager: LeaseManager | None = None):
        self.manager = manager or LeaseManager()

    async def acquire_mailbox(self, tenant_id: str, account_id: str, owner_id: str, ttl_seconds: int = 60) -> Optional[MailboxLease]:
        lease_id = await self.manager.acquire_lease("mailbox", f"{tenant_id}:{account_id}", owner_id, ttl_seconds)
        if not lease_id:
            return None
        return MailboxLease(lease_id, tenant_id, account_id, owner_id)

    async def renew(self, lease: MailboxLease, ttl_seconds: int = 60) -> bool:
        return await self.manager.renew_lease(lease.lease_id, lease.owner_id, ttl_seconds)

    async def release(self, lease: MailboxLease) -> bool:
        return await self.manager.release_lease(lease.lease_id, lease.owner_id)


__all__ = ["MailboxLease", "LeaseOrchestrator"]
