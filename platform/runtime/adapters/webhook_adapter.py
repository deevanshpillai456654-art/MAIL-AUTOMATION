"""
WebhookAdapter — registers and manages webhook endpoints for plugins.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class WebhookAdapter:
    """
    Manages webhook registrations for plugins.
    Proxied through the platform webhooks table.
    """

    def __init__(
        self,
        raw_db: Any,
        plugin_id: str,
        tenant_id: str,
    ) -> None:
        self._db        = raw_db
        self._plugin_id = plugin_id
        self._tenant_id = tenant_id

    def _utc(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def register(
        self,
        url: str,
        events: List[str],
        *,
        secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        webhook_id = f"wh_{uuid.uuid4().hex}"
        secret_val = secret or secrets.token_urlsafe(32)
        now = self._utc()
        self._db.execute(
            """INSERT OR REPLACE INTO webhooks
               (id, connector_id, tenant_id, url, secret, events_json,
                is_active, created_at, last_triggered)
               VALUES (?,?,?,?,?,?,1,?,NULL)""",
            (webhook_id, self._plugin_id, self._tenant_id,
             url, secret_val, json.dumps(events), now),
        )
        return {"webhook_id": webhook_id, "secret": secret_val, "url": url}

    def deregister(self, webhook_id: str) -> None:
        self._db.execute(
            "DELETE FROM webhooks WHERE id=? AND connector_id=? AND tenant_id=?",
            (webhook_id, self._plugin_id, self._tenant_id),
        )

    def list_webhooks(self) -> List[Dict[str, Any]]:
        rows = self._db.fetch_all(
            "SELECT * FROM webhooks WHERE connector_id=? AND tenant_id=?",
            (self._plugin_id, self._tenant_id),
        ) or []
        result = []
        for row in rows:
            d = dict(row)
            d.pop("secret", None)  # never expose secret
            result.append(d)
        return result

    def verify_signature(
        self,
        raw_body: bytes,
        signature_header: str,
        webhook_id: str,
    ) -> bool:
        row = self._db.fetch_one(
            "SELECT secret FROM webhooks WHERE id=? AND connector_id=? AND tenant_id=?",
            (webhook_id, self._plugin_id, self._tenant_id),
        )
        if not row or not row.get("secret"):
            return False
        secret = row["secret"]
        expected = hmac.new(
            secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header.lstrip("sha256="))
