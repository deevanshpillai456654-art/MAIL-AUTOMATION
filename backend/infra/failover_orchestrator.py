"""
Failover orchestration entrypoint (reuses disaster_recovery implementation).
"""

from __future__ import annotations

from .disaster_recovery import (
    BackupManager,
    DROrchestrator,
    DRState,
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
