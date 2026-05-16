"""OAuth state store — replay-protected, UTC-expiry-aware."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict

from backend.db.database import Database


class OAuthStateStore:
    def __init__(self, db: Database):
        self._db = db

    def create(self, provider: str, state: str, code_verifier: str,
               redirect_uri: str, expires_at: str) -> None:
        self._db.create_oauth_state(provider, state, code_verifier, redirect_uri, expires_at)

    def consume(self, provider: str, state: str) -> Optional[Dict]:
        row = self._db.consume_oauth_state(provider, state)
        if not row:
            return None
        expiry_raw = row.get("expires_at")
        if expiry_raw:
            try:
                expiry = datetime.fromisoformat(expiry_raw)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry < datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None
        return row
