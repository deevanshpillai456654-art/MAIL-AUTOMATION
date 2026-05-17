"""
MigrationManager — plugin-isolated database migration runner.

Each plugin manages its own migration version independently.
Migrations are SQL strings keyed by integer version numbers.

Usage::

    mm = MigrationManager(db, plugin_id="salesforce")
    mm.register({
        1: "CREATE TABLE IF NOT EXISTS sf_sync_cursors (id TEXT PRIMARY KEY, cursor TEXT)",
        2: "ALTER TABLE sf_sync_cursors ADD COLUMN updated_at TEXT",
    })
    mm.migrate()  # runs only pending migrations
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

log = logging.getLogger(__name__)


class MigrationManager:
    def __init__(self, db: Any, *, plugin_id: str) -> None:
        self._db        = db
        self._plugin_id = plugin_id
        self._migrations: Dict[int, str] = {}
        self._ensure_meta_table()

    def register(self, migrations: Dict[int, str]) -> None:
        """Register migration SQLs keyed by version number."""
        self._migrations.update(migrations)

    def migrate(self) -> int:
        """
        Run all pending migrations in version order.
        Returns number of migrations applied.
        """
        current = self._current_version()
        pending = sorted(v for v in self._migrations if v > current)
        applied = 0
        for version in pending:
            sql = self._migrations[version]
            log.info("MigrationManager: plugin=%s applying migration v%d", self._plugin_id, version)
            try:
                self._db.execute(sql)
                self._record_version(version)
                applied += 1
            except Exception as exc:
                log.error(
                    "MigrationManager: plugin=%s migration v%d FAILED — %s",
                    self._plugin_id, version, exc,
                )
                raise
        return applied

    def current_version(self) -> int:
        return self._current_version()

    # ── Internal ──────────────────────────────────────────────────────────

    def _ensure_meta_table(self) -> None:
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS plugin_migrations (
               plugin_id   TEXT NOT NULL,
               version     INTEGER NOT NULL,
               applied_at  TEXT NOT NULL,
               PRIMARY KEY (plugin_id, version)
            )"""
        )

    def _current_version(self) -> int:
        row = self._db.fetch_one(
            "SELECT MAX(version) AS v FROM plugin_migrations WHERE plugin_id=?",
            (self._plugin_id,),
        )
        return row["v"] if row and row["v"] is not None else 0

    def _record_version(self, version: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT OR IGNORE INTO plugin_migrations (plugin_id, version, applied_at) VALUES (?,?,?)",
            (self._plugin_id, version, now),
        )
