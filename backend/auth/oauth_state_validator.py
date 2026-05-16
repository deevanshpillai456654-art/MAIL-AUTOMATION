"""OAuth state validation and replay protection."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Dict, Optional
from backend.db.database import Database


class OAuthStateValidator:
    def __init__(self, db: Database):
        self.db = db

    def create_state(self, provider: str, state: str, code_verifier: str, redirect_uri: str, ttl_seconds: int = 600) -> int:
        if not state or len(state) < 24:
            raise ValueError("OAuth state must be high entropy")
        if not redirect_uri.startswith("http://127.0.0.1") and not redirect_uri.startswith("http://localhost"):
            raise ValueError("OAuth redirect URI must be local for this desktop service")
        expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
        return self.db.create_oauth_state(provider, state, code_verifier, redirect_uri, expires_at)

    def consume(self, provider: str, state: str) -> Optional[Dict]:
        if not state:
            return None
        return self.db.consume_oauth_state(provider, state)

    def cleanup(self) -> int:
        before = len(self.db.fetch_all("SELECT id FROM oauth_states WHERE consumed_at IS NULL OR expires_at <= ?", (datetime.now().isoformat(),)))
        self.db.cleanup_oauth_states()
        return before
