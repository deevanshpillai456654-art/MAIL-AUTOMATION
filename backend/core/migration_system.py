"""
Migration System

Features:
- Schema migrations
- Rollback support
- Provider migrations
- AI model migrations
- Config migrations
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("migration.system")


class MigrationType(Enum):
    SCHEMA = "schema"
    DATA = "data"
    PROVIDER = "provider"
    AI_MODEL = "ai_model"
    CONFIG = "config"


class MigrationStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


@dataclass
class Migration:
    """A migration definition"""
    migration_id: str
    version: str
    migration_type: MigrationType
    description: str

    up_func: Optional[Callable] = None
    down_func: Optional[Callable] = None

    dependencies: List[str] = field(default_factory=list)

    status: MigrationStatus = MigrationStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


class MigrationSystem:
    """
    Enterprise migration system with rollback support.
    """

    def __init__(self, migrations_dir: str = "./data/migrations"):
        self.migrations_dir = Path(migrations_dir)
        self.migrations_dir.mkdir(parents=True, exist_ok=True)

        self._migrations: Dict[str, Migration] = {}
        self._current_version: str = "0.0.0"
        self._lock = threading.RLock()

        logger.info("Migration system initialized")

    def register_migration(
        self,
        migration_id: str,
        version: str,
        migration_type: MigrationType,
        description: str,
        up_func: Callable,
        down_func: Optional[Callable] = None,
        dependencies: List[str] = None
    ):
        """Register a migration"""
        migration = Migration(
            migration_id=migration_id,
            version=version,
            migration_type=migration_type,
            description=description,
            up_func=up_func,
            down_func=down_func,
            dependencies=dependencies or []
        )

        self._migrations[migration_id] = migration

        # Update current version if newer
        if self._compare_versions(version, self._current_version) > 0:
            self._current_version = version

        logger.info(f"Registered migration: {migration_id} (v{version})")

    def run_migrations(self, target_version: Optional[str] = None) -> bool:
        """Run pending migrations"""
        target = target_version or self._current_version

        pending = self._get_pending_migrations(target)

        if not pending:
            logger.info("No pending migrations")
            return True

        for migration in pending:
            if not self._run_migration(migration):
                logger.error(f"Migration failed: {migration.migration_id}")
                return False

        return True

    def _run_migration(self, migration: Migration) -> bool:
        """Run a single migration"""
        migration.status = MigrationStatus.RUNNING
        migration.started_at = time.time()

        try:
            if migration.up_func:
                migration.up_func()

            migration.status = MigrationStatus.COMPLETED
            migration.completed_at = time.time()

            # Save state
            self._save_migration_state(migration)

            logger.info(f"Migration completed: {migration.migration_id}")
            return True

        except Exception as e:
            migration.status = MigrationStatus.FAILED
            migration.error = str(e)
            migration.completed_at = time.time()

            logger.error(f"Migration failed: {migration.migration_id}: {e}")
            return False

    def rollback_migration(self, migration_id: str) -> bool:
        """Rollback a migration"""
        migration = self._migrations.get(migration_id)
        if not migration:
            return False

        if not migration.down_func:
            logger.warning(f"Migration has no rollback: {migration_id}")
            return False

        try:
            migration.down_func()

            migration.status = MigrationStatus.ROLLED_BACK
            migration.completed_at = time.time()

            self._save_migration_state(migration)

            logger.info(f"Migration rolled back: {migration_id}")
            return True

        except Exception as e:
            logger.error(f"Rollback failed: {migration_id}: {e}")
            return False

    def _get_pending_migrations(self, target_version: str) -> List[Migration]:
        """Get list of pending migrations"""
        pending = []

        for migration in self._migrations.values():
            if self._compare_versions(migration.version, target_version) <= 0:
                if migration.status != MigrationStatus.COMPLETED:
                    pending.append(migration)

        # Sort by version
        pending.sort(key=lambda m: m.version)

        return pending

    def _compare_versions(self, v1: str, v2: str) -> int:
        """Compare semantic versions"""
        parts1 = [int(p) for p in v1.split(".")]
        parts2 = [int(p) for p in v2.split(".")]

        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0

            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1

        return 0

    def _save_migration_state(self, migration: Migration):
        """Save migration state to file"""
        state_file = self.migrations_dir / "migration_state.json"

        states = {}
        if state_file.exists():
            with open(state_file) as f:
                states = json.load(f)

        states[migration.migration_id] = {
            "version": migration.version,
            "status": migration.status.value,
            "completed_at": migration.completed_at
        }

        with open(state_file, "w") as f:
            json.dump(states, f, indent=2)

    def get_status(self) -> Dict:
        """Get migration status"""
        return {
            "current_version": self._current_version,
            "total_migrations": len(self._migrations),
            "migrations": {
                mid: {
                    "version": m.version,
                    "type": m.migration_type.value,
                    "status": m.status.value,
                    "description": m.description
                }
                for mid, m in self._migrations.items()
            }
        }


# Example migrations
migration_system = MigrationSystem()

def migration_001_schema():
    """Initial schema migration"""
    logger.info("Running schema migration 001")

def migration_001_rollback():
    """Rollback schema migration"""
    logger.info("Rolling back schema migration 001")

migration_system.register_migration(
    "schema_001",
    "9.7.0",
    MigrationType.SCHEMA,
    "Initial schema",
    migration_001_schema,
    migration_001_rollback
)
