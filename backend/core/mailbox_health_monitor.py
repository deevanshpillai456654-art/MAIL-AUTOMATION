"""Mailbox health monitor entry point."""
from __future__ import annotations

from typing import Dict, List

from backend.core.mailbox_health_engine import MailboxHealthEngine
from backend.core.provider_failover_manager import ProviderFailoverManager
from backend.db.database import Database


class MailboxHealthMonitor:
    def __init__(self, db: Database):
        self.db = db
        self.health = MailboxHealthEngine(db)
        self.failover = ProviderFailoverManager(db)

    def scan(self) -> List[Dict]:
        results = []
        for account in self.db.get_all_accounts():
            item = self.health.account_health(account["id"])
            if not item.get("ok"):
                item["failover"] = self.failover.evaluate(account["id"])
            results.append(item)
        return results
