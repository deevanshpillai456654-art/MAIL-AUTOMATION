"""Quarantine corrupted or storming mailboxes instead of retrying forever."""
from __future__ import annotations

from datetime import datetime
from typing import Dict

from backend.db.database import Database


class MailboxQuarantineEngine:
    def __init__(self, db: Database):
        self.db = db
        self._init_tables()

    def _init_tables(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS mailbox_quarantine (
                account_id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL,
                detail TEXT,
                quarantined_at TEXT NOT NULL
            )
        """)

    def quarantine(self, account_id: int, reason: str, detail: str = "") -> Dict:
        self.db.execute("INSERT OR REPLACE INTO mailbox_quarantine (account_id, reason, detail, quarantined_at) VALUES (?, ?, ?, ?)", (account_id, reason, detail, datetime.now().isoformat()))
        self.db.update_account_status(account_id, "quarantined", "quarantined", reason)
        return {"ok": True, "status": "quarantined", "account_id": account_id, "reason": reason}

    def release(self, account_id: int) -> Dict:
        self.db.execute("DELETE FROM mailbox_quarantine WHERE account_id = ?", (account_id,))
        self.db.update_account_status(account_id, "connected", "ok")
        return {"ok": True, "status": "released", "account_id": account_id}

    def is_quarantined(self, account_id: int) -> bool:
        return bool(self.db.fetch_one("SELECT account_id FROM mailbox_quarantine WHERE account_id = ?", (account_id,)))
