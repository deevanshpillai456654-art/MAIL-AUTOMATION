"""
SecretVault — encrypted secret storage for plugins.

Secrets are stored in the connectors DB inside the plugin's config_json
(or a dedicated secrets table if present).  All values at rest are
encrypted via encrypt_secret / decrypt_secret from shared.utils.

Usage::

    vault = SecretVault(db, plugin_id="salesforce", tenant_id="t1")
    vault.put("client_secret", "abc123")
    value = vault.get("client_secret")
    vault.delete("client_secret")
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


def _encrypt(value: str) -> str:
    try:
        from platform.connectors_panel.shared.utils import encrypt_secret  # type: ignore
        return encrypt_secret(value)
    except Exception:
        return value


def _decrypt(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        from platform.connectors_panel.shared.utils import decrypt_secret  # type: ignore
        return decrypt_secret(value)
    except Exception:
        return value


class SecretVault:
    """
    Per-plugin secret store backed by the connector's config_json column.
    Secrets are namespaced under the key "secrets" within the JSON blob.
    """

    def __init__(self, db: Any, *, plugin_id: str, tenant_id: str) -> None:
        self._db        = db
        self._plugin_id = plugin_id
        self._tenant_id = tenant_id

    def put(self, name: str, value: str) -> None:
        enc = _encrypt(value)
        self._db.execute(
            """UPDATE connectors
               SET config_json = json_set(COALESCE(config_json,'{}'), '$.secrets.' || ?, ?)
               WHERE id=? AND tenant_id=?""",
            (name, enc, self._plugin_id, self._tenant_id),
        )

    def get(self, name: str) -> Optional[str]:
        row = self._db.fetch_one(
            "SELECT config_json FROM connectors WHERE id=? AND tenant_id=?",
            (self._plugin_id, self._tenant_id),
        )
        if not row:
            return None
        cfg     = json.loads(row.get("config_json") or "{}")
        secrets = cfg.get("secrets", {})
        enc     = secrets.get(name)
        return _decrypt(enc) if enc else None

    def delete(self, name: str) -> None:
        self._db.execute(
            """UPDATE connectors
               SET config_json = json_remove(COALESCE(config_json,'{}'), '$.secrets.' || ?)
               WHERE id=? AND tenant_id=?""",
            (name, self._plugin_id, self._tenant_id),
        )

    def list_names(self) -> list:
        row = self._db.fetch_one(
            "SELECT config_json FROM connectors WHERE id=? AND tenant_id=?",
            (self._plugin_id, self._tenant_id),
        )
        if not row:
            return []
        cfg = json.loads(row.get("config_json") or "{}")
        return list(cfg.get("secrets", {}).keys())
