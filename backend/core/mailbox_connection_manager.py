"""Mailbox connection and lease management.

This manager provides local idempotency for sync/reconnect operations. It does
not pretend to be a distributed lock; it creates deterministic account-scoped
leases in SQLite so the desktop service cannot schedule duplicate mailbox work
inside the same runtime package.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, Iterator, Optional
import json
import logging

from backend.db.database import Database
from backend.core.provider_capability_registry import ProviderCapabilityRegistry

logger = logging.getLogger(__name__)


class MailboxConnectionManager:
    def __init__(self, db: Database, lease_ttl_seconds: int = 300):
        self.db = db
        self.lease_ttl_seconds = lease_ttl_seconds
        self._init_tables()

    def _init_tables(self) -> None:
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS mailbox_leases (
                lease_key TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                owner TEXT NOT NULL,
                operation TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                metadata TEXT
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_mailbox_leases_account ON mailbox_leases(account_id)")

    def cleanup_expired(self) -> int:
        expired = self.db.fetch_all("SELECT lease_key FROM mailbox_leases WHERE expires_at <= ?", (datetime.now().isoformat(),))
        self.db.execute("DELETE FROM mailbox_leases WHERE expires_at <= ?", (datetime.now().isoformat(),))
        return len(expired)

    def lease_key(self, account_id: int, operation: str) -> str:
        return f"mailbox:{int(account_id)}:{operation}"

    def acquire(self, account_id: int, provider: str, operation: str, owner: str = "backend-service", metadata: Optional[Dict] = None) -> Dict:
        self.cleanup_expired()
        key = self.lease_key(account_id, operation)
        now = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(seconds=self.lease_ttl_seconds)).isoformat()
        try:
            self.db.execute(
                """INSERT INTO mailbox_leases
                   (lease_key, account_id, provider, owner, operation, expires_at, acquired_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, account_id, ProviderCapabilityRegistry.normalize(provider), owner, operation, expires_at, now, json.dumps(metadata or {}, sort_keys=True)),
            )
            return {"ok": True, "status": "acquired", "lease_key": key, "expires_at": expires_at}
        except Exception:
            existing = self.db.fetch_one("SELECT * FROM mailbox_leases WHERE lease_key = ?", (key,))
            return {"ok": False, "status": "busy", "lease_key": key, "existing": existing}

    def release(self, account_id: int, operation: str) -> None:
        self.db.execute("DELETE FROM mailbox_leases WHERE lease_key = ?", (self.lease_key(account_id, operation),))

    @contextmanager
    def account_lease(self, account_id: int, provider: str, operation: str, owner: str = "backend-service") -> Iterator[Dict]:
        lease = self.acquire(account_id, provider, operation, owner)
        try:
            yield lease
        finally:
            if lease.get("ok"):
                self.release(account_id, operation)

