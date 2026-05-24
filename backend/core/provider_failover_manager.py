"""Provider failover decisions for local mailbox operations."""
from __future__ import annotations

from typing import Dict

from backend.core.mailbox_quarantine_engine import MailboxQuarantineEngine
from backend.core.provider_reliability_engine import ProviderReliabilityEngine
from backend.db.database import Database


class ProviderFailoverManager:
    def __init__(self, db: Database):
        self.db = db
        self.reliability = ProviderReliabilityEngine(db)
        self.quarantine = MailboxQuarantineEngine(db)

    def evaluate(self, account_id: int) -> Dict:
        score = self.reliability.score_account(account_id)
        if score.get("score", 0) < 30:
            return self.quarantine.quarantine(account_id, "provider_reliability_too_low", str(score))
        return {"ok": True, "status": "no_failover_required", "account_id": account_id, "score": score}
