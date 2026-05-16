"""Crash-safe local persistence primitives.

The desktop runtime stores operational state locally. These helpers provide a
small, dependency-free persistence layer with atomic writes, journal entries,
backup recovery, and corruption quarantine. They intentionally avoid background
threads so they are safe to use from startup, installers, tests, and recovery
scripts.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class PersistenceValidation:
    status: str
    data_path: str
    backup_path: str
    journal_path: str
    repaired: bool = False
    message: str = "ok"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "data_path": self.data_path,
            "backup_path": self.backup_path,
            "journal_path": self.journal_path,
            "repaired": self.repaired,
            "message": self.message,
        }


class AtomicJSONStore:
    """Atomic JSON store with backup recovery and JSONL write-ahead journal."""

    def __init__(self, root: str | Path, name: str):
        safe_name = Path(name).name
        if not safe_name.endswith(".json"):
            safe_name = f"{safe_name}.json"
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / safe_name
        self.tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self.journal_path = self.path.with_suffix(self.path.suffix + ".journal")
        self._lock = RLock()

    def _append_journal(self, action: str, payload: Optional[Dict[str, Any]] = None) -> None:
        event = {
            "ts": time.time(),
            "action": action,
            "file": self.path.name,
            "payload": payload or {},
        }
        with self.journal_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def _read_json(path: Path) -> Any:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def write(self, data: Any) -> None:
        """Write data atomically and preserve the previous good copy as backup."""
        with self._lock:
            self._append_journal("begin_write", {"bytes_estimate": len(json.dumps(data, default=str))})
            encoded = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            with self.tmp_path.open("w", encoding="utf-8") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())

            # Validate before replacing the active file.
            self._read_json(self.tmp_path)
            previous_backup = self.path.with_suffix(self.path.suffix + ".previous")
            if self.path.exists():
                shutil.copy2(self.path, previous_backup)
            os.replace(self.tmp_path, self.path)
            # Keep the latest known-good active document as the recovery backup.
            # The older copy remains as .previous for one-generation rollback.
            shutil.copy2(self.path, self.backup_path)
            try:
                dir_fd = os.open(str(self.root), os.O_DIRECTORY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except (AttributeError, OSError):
                # Directory fsync is unavailable on some Windows/Python builds.
                pass
            self._append_journal("commit_write", {"size": self.path.stat().st_size})

    def read(self, default: Any = None) -> Any:
        """Read the active JSON file, recovering from backup when needed."""
        with self._lock:
            if not self.path.exists():
                return default
            try:
                return self._read_json(self.path)
            except Exception as exc:
                repaired = self.recover_from_backup(str(exc))
                if repaired:
                    return self._read_json(self.path)
                return default

    def recover_from_backup(self, reason: str = "manual") -> bool:
        """Quarantine corrupt active state and restore the latest valid backup."""
        with self._lock:
            if not self.backup_path.exists():
                self._append_journal("recovery_failed", {"reason": reason, "cause": "missing_backup"})
                return False
            try:
                self._read_json(self.backup_path)
            except Exception as exc:
                self._append_journal("recovery_failed", {"reason": reason, "cause": f"invalid_backup:{exc}"})
                return False
            if self.path.exists():
                corrupt_path = self.path.with_suffix(self.path.suffix + f".corrupt.{int(time.time())}")
                try:
                    os.replace(self.path, corrupt_path)
                except OSError:
                    shutil.copy2(self.path, corrupt_path)
                    self.path.unlink(missing_ok=True)
            shutil.copy2(self.backup_path, self.path)
            self._append_journal("recovered_from_backup", {"reason": reason})
            return True

    def checkpoint(self, checkpoint_name: str, state: Dict[str, Any]) -> Path:
        checkpoints = self.root / "checkpoints"
        store = AtomicJSONStore(checkpoints, checkpoint_name)
        store.write({"checkpoint": checkpoint_name, "created_at": time.time(), "state": state})
        return store.path

    def validate(self) -> PersistenceValidation:
        with self._lock:
            repaired = False
            if self.path.exists():
                try:
                    self._read_json(self.path)
                except Exception as exc:
                    repaired = self.recover_from_backup(str(exc))
                    if not repaired:
                        return PersistenceValidation(
                            status="failed",
                            data_path=str(self.path),
                            backup_path=str(self.backup_path),
                            journal_path=str(self.journal_path),
                            repaired=False,
                            message=f"active JSON is corrupt and backup recovery failed: {exc}",
                        )
            return PersistenceValidation(
                status="ok",
                data_path=str(self.path),
                backup_path=str(self.backup_path),
                journal_path=str(self.journal_path),
                repaired=repaired,
                message="active JSON is valid" if not repaired else "active JSON was restored from backup",
            )


__all__ = ["AtomicJSONStore", "PersistenceValidation"]
