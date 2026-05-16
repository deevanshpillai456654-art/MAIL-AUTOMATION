"""
Restore verification: checksum re-validation and dry-run restore probes.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

from .disaster_recovery import BackupManager

logger = logging.getLogger("backup_validator")


class BackupValidator:
    def __init__(self, backup_manager: Optional[BackupManager] = None):
        self._bm = backup_manager or BackupManager(storage_path=str(Path("data") / "backups"))
        self._lock = threading.Lock()

    def validate_registered(self, backup_id: str) -> Tuple[bool, str]:
        ok = self._bm.verify_backup(backup_id)
        return ok, "verified" if ok else "checksum_mismatch"

    def probe_restore(
        self,
        artifact_path: Path,
        checksum_fn: Callable[[Path], str],
        expected_hex: str,
    ) -> Tuple[bool, str]:
        if not artifact_path.exists():
            return False, "missing"
        digest = checksum_fn(artifact_path)
        ok = digest.lower() == expected_hex.lower()
        return ok, digest


__all__ = ["BackupValidator"]
