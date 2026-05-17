"""
AuthSDK — OAuth token management and API key storage for plugins.

Usage::

    sdk = AuthSDK(context)

    # OAuth flow
    url = await sdk.get_oauth_url(redirect_uri, state)
    tokens = await sdk.exchange_code(code, redirect_uri)
    access_token = await sdk.get_valid_token()

    # API keys
    sdk.store_api_key("sk_live_xxx")
    key = sdk.get_api_key()
"""
from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class AuthSDK:
    """
    Provides token storage, retrieval, and refresh logic for plugins.

    Backed by the platform oauth_tokens table.
    The raw db is accessed via the context.db adapter.
    """

    def __init__(self, context: Any) -> None:
        self._ctx = context

    @property
    def _db(self) -> Optional[Any]:
        return getattr(self._ctx, "db", None)

    def _utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _encrypt(self, value: str) -> str:
        try:
            from platform.connectors_panel.shared.utils import encrypt_secret  # type: ignore
            return encrypt_secret(value)
        except Exception:
            return value

    def _decrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            from platform.connectors_panel.shared.utils import decrypt_secret  # type: ignore
            return decrypt_secret(value)
        except Exception:
            return value

    # ── Token storage ─────────────────────────────────────────────────────

    def store_tokens(
        self,
        access_token: str,
        *,
        refresh_token: Optional[str] = None,
        expires_in_seconds: Optional[int] = None,
        scopes: Optional[List[str]] = None,
    ) -> str:
        if not self._db:
            raise RuntimeError("AuthSDK: no DB adapter available")

        plugin_id = getattr(self._ctx, "plugin_id", "unknown")
        tenant_id = getattr(self._ctx, "tenant_id", "__system__")
        now = self._utc()
        token_id = f"tok_{uuid.uuid4().hex}"
        expires_at = None
        if expires_in_seconds:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(seconds=expires_in_seconds)
            ).isoformat()

        self._db.execute(
            """INSERT OR REPLACE INTO oauth_tokens
               (id, connector_id, tenant_id, provider,
                access_token_enc, refresh_token_enc,
                expires_at, scopes, is_valid, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)
               ON CONFLICT(connector_id, tenant_id, provider)
               DO UPDATE SET
                 access_token_enc=excluded.access_token_enc,
                 refresh_token_enc=excluded.refresh_token_enc,
                 expires_at=excluded.expires_at,
                 scopes=excluded.scopes,
                 is_valid=1""",
            (
                token_id, plugin_id, tenant_id, plugin_id,
                self._encrypt(access_token),
                self._encrypt(refresh_token) if refresh_token else None,
                expires_at,
                json.dumps(scopes or []),
                now,
            ),
        )
        return token_id

    def get_tokens(self) -> Optional[Dict[str, Any]]:
        if not self._db:
            return None
        plugin_id = getattr(self._ctx, "plugin_id", "unknown")
        tenant_id = getattr(self._ctx, "tenant_id", "__system__")
        row = self._db.fetch_one(
            "SELECT * FROM oauth_tokens WHERE connector_id=? AND tenant_id=? AND provider=? AND is_valid=1",
            (plugin_id, tenant_id, plugin_id),
        )
        if not row:
            return None
        tok = dict(row)
        tok["access_token"]  = self._decrypt(tok.pop("access_token_enc", None))
        tok["refresh_token"] = self._decrypt(tok.pop("refresh_token_enc", None))
        return tok

    async def get_valid_token(self) -> Optional[str]:
        """Return a valid access token, refreshing if < 5 minutes remain."""
        tok = self.get_tokens()
        if not tok:
            return None
        if tok.get("expires_at"):
            try:
                exp = datetime.fromisoformat(tok["expires_at"].replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                remaining = (exp - datetime.now(timezone.utc)).total_seconds()
                if remaining < 300 and tok.get("refresh_token"):
                    return await self.refresh_token(tok["refresh_token"])
            except Exception:
                pass
        return tok.get("access_token")

    async def refresh_token(self, refresh_token: str) -> Optional[str]:
        """Override in subclass or set refresh_handler."""
        plugin = getattr(self._ctx, "plugin_instance", None)
        if plugin and hasattr(plugin, "refresh_access_token"):
            return await plugin.refresh_access_token()
        log.warning("AuthSDK: no refresh handler — returning None")
        return None

    def invalidate(self) -> None:
        if not self._db:
            return
        plugin_id = getattr(self._ctx, "plugin_id", "unknown")
        tenant_id = getattr(self._ctx, "tenant_id", "__system__")
        self._db.execute(
            "UPDATE oauth_tokens SET is_valid=0 WHERE connector_id=? AND tenant_id=?",
            (plugin_id, tenant_id),
        )

    # ── API key ───────────────────────────────────────────────────────────

    def store_api_key(self, api_key: str, name: str = "default") -> None:
        """Persist an encrypted API key in the connector config."""
        if not self._db:
            return
        plugin_id = getattr(self._ctx, "plugin_id", "unknown")
        tenant_id = getattr(self._ctx, "tenant_id", "__system__")
        self._db.execute(
            """UPDATE connectors SET config_json = json_set(COALESCE(config_json,'{}'),
               '$.api_key_enc', ?)
               WHERE id=? AND tenant_id=?""",
            (self._encrypt(api_key), plugin_id, tenant_id),
        )

    def get_api_key(self) -> Optional[str]:
        if not self._db:
            return None
        plugin_id = getattr(self._ctx, "plugin_id", "unknown")
        tenant_id = getattr(self._ctx, "tenant_id", "__system__")
        row = self._db.fetch_one(
            "SELECT config_json FROM connectors WHERE id=? AND tenant_id=?",
            (plugin_id, tenant_id),
        )
        if not row:
            return None
        cfg = json.loads(row.get("config_json") or "{}")
        enc = cfg.get("api_key_enc")
        return self._decrypt(enc) if enc else None
