import os
import sys
import json
import sqlite3
import hashlib
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Callable
from abc import ABC, abstractmethod


class Migration(ABC):
    def __init__(self, version: str, description: str):
        self.version = version
        self.description = description
        self.timestamp = datetime.now().isoformat()

    @abstractmethod
    def up(self, db_connection) -> bool:
        return False

    @abstractmethod
    def down(self, db_connection) -> bool:
        return False


class AddUsersTableMigration(Migration):
    def __init__(self):
        super().__init__("9.7.0", "Add users table")

    def up(self, conn) -> bool:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP
            )
        """)
        conn.commit()
        return True

    def down(self, conn) -> bool:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS users")
        conn.commit()
        return True


class AddIndexesMigration(Migration):
    def __init__(self):
        super().__init__("9.7.1", "Add performance indexes")

    def up(self, conn) -> bool:
        cursor = conn.cursor()
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_labels_name ON labels(name)")
        conn.commit()
        return True

    def down(self, conn) -> bool:
        cursor = conn.cursor()
        cursor.execute("DROP INDEX IF EXISTS idx_emails_date")
        cursor.execute("DROP INDEX IF EXISTS idx_emails_sender")
        cursor.execute("DROP INDEX IF EXISTS idx_labels_name")
        conn.commit()
        return True


class AddSettingsTableMigration(Migration):
    def __init__(self):
        super().__init__("9.7.2", "Add settings table")

    def up(self, conn) -> bool:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        return True

    def down(self, conn) -> bool:
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS settings")
        conn.commit()
        return True


class MigrationEngine:
    def __init__(self, app_name="AIEmailOrganizer"):
        self.app_name = app_name
        self.install_path = self._get_install_path()
        self.runtime_home = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or self.install_path,
            self.app_name,
        )
        self.db_path = os.path.join(self.runtime_home, "data", "emails.db")
        self.migration_path = os.path.join(self.runtime_home, "data", "migrations")
        self.schema_version_file = os.path.join(self.migration_path, "schema_version.json")
        self.log_file = os.path.join(self.runtime_home, "logs", "migrations.log")

        os.makedirs(self.migration_path, exist_ok=True)
        self.migrations = self._register_migrations()

    def _get_install_path(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"Software\\{self.app_name}", 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "InstallPath")
            winreg.CloseKey(key)
            return value
        except Exception:
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _register_migrations(self) -> List[Migration]:
        return [
            AddUsersTableMigration(),
            AddIndexesMigration(),
            AddSettingsTableMigration(),
        ]

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        print(log_entry)
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, "a") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass

    def get_current_version(self) -> str:
        if os.path.exists(self.schema_version_file):
            try:
                with open(self.schema_version_file, "r") as f:
                    data = json.load(f)
                    return data.get("version", "9.7.0")
            except Exception:
                pass
        return "9.7.0"

    def get_pending_migrations(self) -> List[Migration]:
        current = self.get_current_version()
        pending = []
        for migration in self.migrations:
            if self._compare_versions(migration.version, current) > 0:
                pending.append(migration)
        return pending

    def _compare_versions(self, v1: str, v2: str) -> int:
        parts1 = [int(x) for x in v1.split('.')]
        parts2 = [int(x) for x in v2.split('.')]
        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0
            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1
        return 0

    def run_migrations(self, dry_run: bool = False) -> bool:
        self.log("Starting migrations...")
        pending = self.get_pending_migrations()

        if not pending:
            self.log("No pending migrations")
            return True

        self.log(f"Found {len(pending)} pending migrations")

        if dry_run:
            self.log("DRY RUN MODE - No changes will be made")
            for m in pending:
                print(f"  Would apply: {m.version} - {m.description}")
            return True

        try:
            if not os.path.exists(self.db_path):
                self._create_initial_database()

            conn = sqlite3.connect(self.db_path)

            for migration in pending:
                self.log(f"Applying migration: {migration.version} - {migration.description}")
                if migration.up(conn):
                    self._update_schema_version(migration.version)
                    self.log(f"Migration {migration.version} applied successfully")
                else:
                    self.log(f"Migration {migration.version} failed", "ERROR")
                    conn.rollback()
                    conn.close()
                    return False

            conn.close()
            self.log("All migrations completed successfully")
            return True

        except Exception as e:
            self.log(f"Migration failed: {e}", "ERROR")
            return False

    def _create_initial_database(self):
        self.log("Creating initial database...")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT,
                sender TEXT,
                recipient TEXT,
                date TIMESTAMP,
                body TEXT,
                folder TEXT DEFAULT 'inbox',
                read INTEGER DEFAULT 0,
                starred INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                color TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        self.log("Initial database created")

    def _update_schema_version(self, version: str):
        with open(self.schema_version_file, "w") as f:
            json.dump({
                "version": version,
                "updated_at": datetime.now().isoformat()
            }, f, indent=2)

    def rollback_migration(self, target_version: str = None) -> bool:
        self.log("Starting migration rollback...")
        current = self.get_current_version()

        if target_version is None:
            applied = self.get_applied_migrations()
            if len(applied) < 2:
                self.log("No previous migration to rollback to", "ERROR")
                return False
            target_version = applied[-2]["version"]

        self.log(f"Rolling back to version: {target_version}")

        try:
            conn = sqlite3.connect(self.db_path)

            for migration in reversed(self.migrations):
                if self._compare_versions(migration.version, current) <= 0 and \
                   self._compare_versions(migration.version, target_version) > 0:
                    self.log(f"Rolling back: {migration.version}")
                    if migration.down(conn):
                        self.log(f"Rolled back {migration.version}")
                    else:
                        self.log(f"Failed to rollback {migration.version}", "ERROR")
                        conn.rollback()
                        return False

            conn.close()
            self._update_schema_version(target_version)
            self.log("Rollback completed")
            return True

        except Exception as e:
            self.log(f"Rollback failed: {e}", "ERROR")
            return False

    def get_applied_migrations(self) -> List[Dict]:
        history_file = os.path.join(self.migration_path, "migration_history.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def test_migration(self, migration: Migration) -> bool:
        self.log(f"Testing migration: {migration.version}")
        try:
            if not os.path.exists(self.db_path):
                self._create_initial_database()

            conn = sqlite3.connect(self.db_path)

            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM emails")
            initial_count = cursor.fetchone()[0]

            if not migration.up(conn):
                self.log("Test migration up failed", "ERROR")
                return False

            cursor.execute("SELECT COUNT(*) FROM emails")
            after_count = cursor.fetchone()[0]

            if not migration.down(conn):
                self.log("Test migration down failed", "ERROR")
                return False

            cursor.execute("SELECT COUNT(*) FROM emails")
            final_count = cursor.fetchone()[0]

            conn.close()

            if initial_count == final_count:
                self.log("Migration test passed")
                return True
            else:
                self.log("Migration test failed - data not restored", "ERROR")
                return False

        except Exception as e:
            self.log(f"Migration test crashed: {e}", "ERROR")
            return False


def main():
    engine = MigrationEngine()

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "migrate":
            dry_run = "--dry-run" in sys.argv
            if engine.run_migrations(dry_run=dry_run):
                print("Migration completed successfully")
            else:
                print("Migration failed")
        elif command == "rollback":
            target = sys.argv[2] if len(sys.argv) > 2 else None
            if engine.rollback_migration(target):
                print("Rollback completed")
            else:
                print("Rollback failed")
        elif command == "status":
            print(f"Current schema version: {engine.get_current_version()}")
            pending = engine.get_pending_migrations()
            if pending:
                print(f"Pending migrations: {len(pending)}")
                for m in pending:
                    print(f"  {m.version} - {m.description}")
            else:
                print("No pending migrations")
        elif command == "test":
            for migration in engine.migrations:
                if engine.test_migration(migration):
                    print(f"PASSED: {migration.version}")
                else:
                    print(f"FAILED: {migration.version}")
    else:
        print("Usage: migration_engine.py <command>")
        print("Commands: migrate, rollback, status, test")


if __name__ == "__main__":
    main()