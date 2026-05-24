"""Auth health aggregation."""
from __future__ import annotations

from typing import Dict, List

from backend.auth.provider_token_manager import ProviderTokenManager
from backend.db.database import Database


class ProviderAuthHealth:
    def __init__(self, db: Database):
        self.db = db
        self.tokens = ProviderTokenManager(db)

    def account(self, account_id: int) -> Dict:
        return self.tokens.token_health(account_id)

    def all_accounts(self) -> List[Dict]:
        return [{"account_id": row["id"], **self.account(row["id"])} for row in self.db.get_all_accounts()]
