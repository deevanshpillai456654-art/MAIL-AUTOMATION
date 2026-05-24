"""Sync recovery helpers that avoid duplicate execution."""
from __future__ import annotations

from typing import Dict

from backend.core.mailbox_connection_manager import MailboxConnectionManager
from backend.core.mailbox_recovery_engine import MailboxRecoveryEngine
from backend.db.database import Database


class MailboxSyncRecovery:
    def __init__(self, db: Database):
        self.db = db
        self.leases = MailboxConnectionManager(db)
        self.recovery = MailboxRecoveryEngine(db)

    def recover_failed_sync(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        with self.leases.account_lease(account_id, account["provider"], "recovery") as lease:
            if not lease.get("ok"):
                return {"ok": False, "status": "recovery_already_running", "lease": lease}
            return self.recovery.recover(account_id)
