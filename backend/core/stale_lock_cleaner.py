"""Periodic stale lock and lease cleanup."""
from __future__ import annotations

from dataclasses import dataclass

from .lease_manager import DistributedLockManager, LeaseManager


@dataclass
class CleanupResult:
    expired_locks: int
    reclaimed_leases: int


class StaleLockCleaner:
    def __init__(self, lock_manager: DistributedLockManager, lease_manager: LeaseManager):
        self.lock_manager = lock_manager
        self.lease_manager = lease_manager

    def run_once(self) -> CleanupResult:
        expired_locks = self.lock_manager.sweep_expired_locks()
        reclaimed = len(self.lease_manager.reclaim_expired())
        return CleanupResult(expired_locks=expired_locks, reclaimed_leases=reclaimed)


__all__ = ["CleanupResult", "StaleLockCleaner"]
