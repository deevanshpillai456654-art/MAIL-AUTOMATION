"""
Orphan and zombie recovery: bridges job coordinator, leases, and optional locks.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .control_plane import ControlPlane, get_control_plane
from .job_coordinator import JobCoordinator, get_job_coordinator

logger = logging.getLogger("orphan_recovery")


class OrphanRecoveryOrchestrator:
    def __init__(
        self,
        jobs: Optional[JobCoordinator] = None,
        control_plane: Optional[ControlPlane] = None,
    ):
        self._jobs = jobs or get_job_coordinator()
        self._cp = control_plane or get_control_plane()
        self._lock = threading.RLock()

    def run_cycle(self) -> Dict[str, Any]:
        recovered_jobs = self._jobs.recover_orphaned_jobs()
        stale_leases = self._cp.sweep_stale_leases()
        lock_swept = self._cp.sweep_expired_locks()
        return {
            "recovered_jobs": recovered_jobs,
            "reclaimed_leases": stale_leases,
            "expired_locks_removed": lock_swept,
            "ts": time.time(),
        }


__all__ = ["OrphanRecoveryOrchestrator"]
