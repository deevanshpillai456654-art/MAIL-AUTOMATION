"""
Distributed-style locks and leases for a single process or adapter-backed deployment.

TTL extension for the same owner prevents stale self-locking. Cross-process safety
requires Redis or another shared atomic store wired into DistributedLockManager.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("lease_manager")


class LockType(Enum):
    WORKFLOW = "workflow"
    JOB = "job"
    PROVIDER = "provider"
    TENANT = "tenant"
    RESOURCE = "resource"


@dataclass
class DistributedLock:
    lock_id: str
    lock_type: LockType
    owner_id: str
    resource_id: str
    acquired_at: float
    expires_at: float
    ttl_seconds: int


@dataclass
class Lease:
    lease_id: str
    resource_type: str
    resource_id: str
    owner_id: str
    heartbeat_deadline: float
    acquired_at: float


class DistributedLockManager:
    def __init__(self, redis_client: Optional[object] = None) -> None:
        self._redis = redis_client
        self._local_locks: Dict[str, DistributedLock] = {}
        self._lock = threading.RLock()

    async def acquire_lock(
        self,
        lock_type: LockType,
        resource_id: str,
        owner_id: str,
        ttl_seconds: int = 60,
    ) -> Optional[str]:
        if self._redis is not None:
            raise RuntimeError("Redis-backed locks are not configured in this build; pass redis_client=None.")

        lock_id = f"{lock_type.value}:{resource_id}"
        now = time.time()
        with self._lock:
            existing = self._local_locks.get(lock_id)
            if existing:
                if existing.expires_at > now:
                    if existing.owner_id == owner_id:
                        existing.expires_at = now + ttl_seconds
                        existing.ttl_seconds = ttl_seconds
                        return lock_id
                    return None
                del self._local_locks[lock_id]

            lock = DistributedLock(
                lock_id=lock_id,
                lock_type=lock_type,
                owner_id=owner_id,
                resource_id=resource_id,
                acquired_at=now,
                expires_at=now + ttl_seconds,
                ttl_seconds=ttl_seconds,
            )
            self._local_locks[lock_id] = lock
            logger.info("Lock acquired %s by %s", lock_id, owner_id)
            return lock_id

    async def release_lock(self, lock_id: str, owner_id: str) -> bool:
        with self._lock:
            if lock_id not in self._local_locks:
                return False
            lock = self._local_locks[lock_id]
            if lock.owner_id != owner_id:
                return False
            del self._local_locks[lock_id]
            logger.info("Lock released %s", lock_id)
            return True

    def is_locked(self, lock_type: LockType, resource_id: str) -> bool:
        lock_id = f"{lock_type.value}:{resource_id}"
        with self._lock:
            lock = self._local_locks.get(lock_id)
            return bool(lock and lock.expires_at > time.time())

    def sweep_expired_locks(self) -> int:
        now = time.time()
        with self._lock:
            expired = [lid for lid, l in self._local_locks.items() if l.expires_at <= now]
            for lid in expired:
                del self._local_locks[lid]
            return len(expired)


class LeaseManager:
    def __init__(self, default_ttl_seconds: float = 60.0) -> None:
        self._leases: Dict[str, Lease] = {}
        self._lock = threading.RLock()
        self._default_ttl = default_ttl_seconds

    async def acquire_lease(
        self,
        resource_type: str,
        resource_id: str,
        owner_id: str,
        ttl_seconds: int = 60,
    ) -> Optional[str]:
        lease_id = f"{resource_type}:{resource_id}"
        now = time.time()
        deadline = now + float(ttl_seconds)
        with self._lock:
            cur = self._leases.get(lease_id)
            if cur:
                if cur.heartbeat_deadline > now and cur.owner_id != owner_id:
                    return None
                if cur.owner_id == owner_id:
                    cur.heartbeat_deadline = deadline
                    return lease_id
                if cur.heartbeat_deadline <= now:
                    del self._leases[lease_id]

            self._leases[lease_id] = Lease(
                lease_id=lease_id,
                resource_type=resource_type,
                resource_id=resource_id,
                owner_id=owner_id,
                heartbeat_deadline=deadline,
                acquired_at=now,
            )
            logger.info("Lease acquired %s by %s", lease_id, owner_id)
            return lease_id

    async def renew_lease(self, lease_id: str, owner_id: str, ttl_seconds: int = 60) -> bool:
        with self._lock:
            if lease_id not in self._leases:
                return False
            lease = self._leases[lease_id]
            if lease.owner_id != owner_id:
                return False
            lease.heartbeat_deadline = time.time() + float(ttl_seconds)
            return True

    async def release_lease(self, lease_id: str, owner_id: str) -> bool:
        with self._lock:
            if lease_id not in self._leases:
                return False
            lease = self._leases[lease_id]
            if lease.owner_id != owner_id:
                return False
            del self._leases[lease_id]
            logger.info("Lease released %s", lease_id)
            return True

    def get_orphaned_leases(self) -> List[str]:
        now = time.time()
        with self._lock:
            return [lid for lid, lease in self._leases.items() if lease.heartbeat_deadline <= now]

    def reclaim_expired(self) -> List[str]:
        orphaned = self.get_orphaned_leases()
        with self._lock:
            for lid in orphaned:
                self._leases.pop(lid, None)
        return orphaned

    def is_owned(self, resource_type: str, resource_id: str) -> bool:
        lease_id = f"{resource_type}:{resource_id}"
        with self._lock:
            lease = self._leases.get(lease_id)
            return bool(lease and lease.heartbeat_deadline > time.time())


__all__ = [
    "LockType",
    "DistributedLock",
    "Lease",
    "DistributedLockManager",
    "LeaseManager",
]
