"""Encrypted token storage with UTC expiry and refresh preservation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from backend import config
from backend.auth.token_crypto import TokenCipher
from backend.db.database import Database


class TokenStore:
    def __init__(self, db: Database, cipher: TokenCipher = None):
        self._db = db
        self._cipher = cipher or TokenCipher()

    def save(self, account_id: int, access_token: str,
             refresh_token: Optional[str] = None, expires_in: int = None) -> None:
        enc_access = self._cipher.encrypt(access_token)
        enc_refresh = self._cipher.encrypt(refresh_token) if refresh_token else None
        ttl = expires_in or config.TOKEN_EXPIRY_SECONDS
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        self._db.update_account_tokens(account_id, enc_access, enc_refresh, expires_at)

    def get_access_token(self, account_id: int) -> Optional[str]:
        account = self._db.get_account_by_id(account_id)
        if not account or not account.get("access_token"):
            return None
        expiry_raw = account.get("token_expiry")
        if expiry_raw:
            try:
                expiry = datetime.fromisoformat(expiry_raw)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry > datetime.now(timezone.utc):
                    return self._cipher.decrypt(account["access_token"])
            except ValueError:
                pass
        return None

    def get_refresh_token(self, account_id: int) -> Optional[str]:
        account = self._db.get_account_by_id(account_id)
        if account and account.get("refresh_token"):
            return self._cipher.decrypt(account["refresh_token"])
        return None
