"""Durable local migration engine for AIEmailOrganizer v9.7.

Stores migration state under the user's runtime profile, not the install folder,
so account databases and migrations survive Windows restart and application
upgrades.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

APP_VERSION = "9.7.0"
APP_NAME = "AIEmailOrganizer"


def runtime_home() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME


class MigrationEngine:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else runtime_home()
        self.data_dir = self.root / "data"
        self.migration_dir = self.data_dir / "migrations"
        self.state_path = self.migration_dir / "migration_state_v9_1.json"
        self.migration_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"version": APP_VERSION, "applied": [], "updated_at": None}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            corrupt = self.state_path.with_suffix(".corrupt.json")
            try:
                self.state_path.replace(corrupt)
            except Exception:
                pass
            return {"version": APP_VERSION, "applied": [], "updated_at": None, "recovered_corrupt_state": True}

    def _save(self, state: Dict[str, Any]) -> None:
        state["version"] = APP_VERSION
        state["updated_at"] = time.time()
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def status(self) -> Dict[str, Any]:
        state = self._load()
        return {
            "version": APP_VERSION,
            "status": "ready",
            "runtime_home": str(self.root),
            "data_dir": str(self.data_dir),
            "migration_dir": str(self.migration_dir),
            "applied_count": len(state.get("applied", [])),
            "state_path": str(self.state_path),
        }

    def apply_marker(self, migration_id: str, details: Dict[str, Any] | None = None) -> Dict[str, Any]:
        state = self._load()
        applied: List[Dict[str, Any]] = list(state.get("applied", []))
        if not any(item.get("id") == migration_id for item in applied):
            applied.append({"id": migration_id, "details": details or {}, "applied_at": time.time()})
        state["applied"] = applied
        self._save(state)
        return self.status()


def get_migration_engine() -> MigrationEngine:
    return MigrationEngine()
