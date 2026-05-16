"""Provider reliability scoring based on local diagnostics and sync history."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, List
from backend.db.database import Database


class ProviderReliabilityEngine:
    def __init__(self, db: Database):
        self.db = db

    def score_account(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "score": 0, "status": "missing"}
        syncs = self.db.fetch_all("SELECT * FROM sync_status WHERE account_id = ? ORDER BY started_at DESC LIMIT 20", (account_id,))
        diagnostics = self.db.fetch_all("SELECT * FROM provider_diagnostics WHERE account_id = ? ORDER BY checked_at DESC LIMIT 20", (account_id,))
        score = 100
        failed_syncs = sum(1 for row in syncs if row.get("status") == "failed")
        degraded = account.get("status") in {"degraded", "needs_reconnect"}
        score -= min(50, failed_syncs * 10)
        if degraded:
            score -= 25
        negative = sum(1 for row in diagnostics if row.get("status") not in {"connected", "healthy", "token_ok", "ok"})
        score -= min(25, negative * 5)
        score = max(0, min(100, score))
        return {"ok": score >= 60, "score": score, "status": "healthy" if score >= 80 else "degraded" if score >= 60 else "unhealthy", "failed_syncs": failed_syncs, "diagnostic_warnings": negative}

    def provider_scores(self) -> List[Dict]:
        return [{"account_id": account["id"], "provider": account["provider"], **self.score_account(account["id"])} for account in self.db.get_all_accounts()]
