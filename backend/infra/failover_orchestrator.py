"""
Failover orchestration entrypoint (reuses disaster_recovery implementation).
"""

from __future__ import annotations

from .disaster_recovery import (
    DRState,
    BackupManager,
    DROrchestrator,
    FailoverOrchestrator,
    get_dr_orchestrator,
)

__all__ = [
    "DRState",
    "BackupManager",
    "FailoverOrchestrator",
    "DROrchestrator",
    "get_dr_orchestrator",
]
