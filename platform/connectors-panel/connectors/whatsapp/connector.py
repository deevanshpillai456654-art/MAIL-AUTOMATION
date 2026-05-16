"""
WhatsApp Business Connector — Meta Graph API v17.
Multi-agent inbox, media, templates, CRM linking, shipment notifications.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import (
    ConnectorManifest, OAuthConfig, WebhookConfig,
    SyncConfig, Permission,
)

MANIFEST = ConnectorManifest(
    id="whatsapp",
    name="WhatsApp Business",
    category="communication",
    description="Multi-agent inbox, templates, media, CRM linking and AI routing.",
    version="2.0.0",
    icon="💬",
    supports_oauth=True,
    supports_webhook=True,
    supports_api_key=True,
    oauth=OAuthConfig(
        provider_id="whatsapp_business",
        auth_url="https://www.facebook.com/v17.0/dialog/oauth",
        token_url="https://graph.facebook.com/v17.0/oauth/access_token",
        scopes=["whatsapp_business_management", "whatsapp_business_messaging"],
        supports_refresh=False,
    ),
    webhook=WebhookConfig(
        events=["messages", "message_status", "business_capability_update"],
        signature_header="X-Hub-Signature-256",
    ),
    sync=SyncConfig(
        entities=["templates", "conversations"],
        default_interval_seconds=3600,
    ),
    permissions=[
        Permission("whatsapp_business_messaging", "Send Messages", "Send WhatsApp messages"),
        Permission("whatsapp_business_management", "Manage Business", "Manage WABA settings"),
    ],
    config_schema={
        "phone_number_id": {"type": "string", "required": True},
        "waba_id": {"type": "string", "required": True},
        "access_token": {"type": "string", "required": True, "secret": True},
        "verify_token": {"type": "string", "required": True, "secret": True},
        "app_secret": {"type": "string", "required": True, "secret": True},
    },
    emits_events=[
        "whatsapp.message.received", "whatsapp.message.sent",
        "whatsapp.status.updated", "whatsapp.media.received",
    ],
)

GRAPH_BASE = "https://graph.facebook.com/v17.0"


class WhatsAppConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 80.0  # Meta: 80 msg/s per WABA
    RATE_BURST = 100.0

    def _phone_id(self) -> str:
        return self.config.get("phone_number_id", "")

    def _token(self) -> str:
        # WhatsApp uses long-lived page tokens, stored in config
        return self.config.get("access_token", "")

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = urlencode({
            "client_id": self.config.get("app_id", ""),
            "redirect_uri": redirect_uri,
            "scope": "whatsapp_business_management,whatsapp_business_messaging",
            "state": state,
            "response_type": "code",
        })
        return f"https://www.facebook.com/v17.0/dialog/oauth?{params}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        resp = await client.get(
            f"{GRAPH_BASE}/oauth/access_token",
            params={
                "client_id": self.config.get("app_id", ""),
                "client_secret": self.config.get("app_secret", ""),
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._store_token(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=None,
            scopes=["whatsapp_business_management", "whatsapp_business_messaging"],
        )
        return data

    async def send_text(self, to: str, body: str) -> Dict:
        client = self._get_http()
        resp = await client.post(
            f"{GRAPH_BASE}/{self._phone_id()}/messages",
            headers={"Authorization": f"Bearer {self._token()}",
                     "Content-Type": "application/json"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body},
            },
        )
        resp.raise_for_status()
        result = resp.json()
        self._publish_event("whatsapp.message.sent",
                            {"to": to, "message_id": result.get("messages", [{}])[0].get("id")})
        return result

    async def send_template(self, to: str, template_name: str,
                            language_code: str = "en_US",
                            components: Optional[List] = None) -> Dict:
        client = self._get_http()
        payload: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
            },
        }
        if components:
            payload["template"]["components"] = components
        resp = await client.post(
            f"{GRAPH_BASE}/{self._phone_id()}/messages",
            headers={"Authorization": f"Bearer {self._token()}",
                     "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_templates(self) -> List[Dict]:
        client = self._get_http()
        resp = await client.get(
            f"{GRAPH_BASE}/{self.config.get('waba_id', '')}/message_templates",
            headers={"Authorization": f"Bearer {self._token()}"},
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "templates":
            templates = await self.get_templates()
            return {"synced": len(templates), "entity": "templates"}
        return {"synced": 0, "entity": entity}

    async def verify_webhook_signature(self, raw_body: bytes,
                                       headers: Dict[str, str]) -> bool:
        app_secret = self.config.get("app_secret", "")
        sig_header = headers.get("X-Hub-Signature-256", "")
        if not sig_header:
            return False
        expected = "sha256=" + hmac.new(
            app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict[str, str]) -> None:
        # Handle webhook verification challenge
        if event_type == "GET":
            return

        try:
            entry = payload.get("entry", [])
            for e in entry:
                for change in e.get("changes", []):
                    value = change.get("value", {})
                    # Inbound messages
                    for msg in value.get("messages", []):
                        msg_type = msg.get("type", "text")
                        from_number = msg.get("from", "")
                        msg_id = msg.get("id", "")
                        text = msg.get("text", {}).get("body", "")

                        # Store in support tickets if configured
                        self._create_or_update_ticket(from_number, text, msg_id, msg_type)

                        self._publish_event("whatsapp.message.received", {
                            "from": from_number,
                            "message_id": msg_id,
                            "type": msg_type,
                            "text": text,
                            "timestamp": msg.get("timestamp"),
                        })

                    # Status updates
                    for status in value.get("statuses", []):
                        self._publish_event("whatsapp.status.updated", {
                            "message_id": status.get("id"),
                            "status": status.get("status"),
                            "recipient": status.get("recipient_id"),
                        })
        except Exception as exc:
            self._log("ERROR", f"WhatsApp webhook processing error: {exc}")

    def _create_or_update_ticket(self, from_number: str, text: str,
                                 msg_id: str, msg_type: str) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        # Find open WhatsApp ticket for this number
        existing = self.db.fetch_one(
            """SELECT ticket_id FROM support_tickets
               WHERE customer_phone=? AND channel='whatsapp'
               AND status NOT IN ('resolved','closed')
               AND tenant_id=?
               ORDER BY created_at DESC LIMIT 1""",
            (from_number, self.tenant_id),
        ) if self.db.fetch_one.__code__.co_varcount > 0 else None

        try:
            if existing:
                ticket_id = existing["ticket_id"]
            else:
                ticket_id = f"tkt_{uuid.uuid4().hex}"
                ticket_num = f"WA-{ticket_id[-6:].upper()}"
                from datetime import timedelta
                sla_due = (datetime.now(tz=timezone.utc) + timedelta(hours=24)).isoformat()
                self.db.execute(
                    """INSERT INTO support_tickets
                       (ticket_id, tenant_id, ticket_number, subject, customer_phone,
                        channel, status, priority, sla_due_at, created_at, updated_at)
                       VALUES (?,?,?,?,?,'whatsapp','open','normal',?,?,?)""",
                    (ticket_id, self.tenant_id, ticket_num,
                     f"WhatsApp: {text[:80]}", from_number,
                     sla_due, now, now),
                )
            # Add message
            msg_rec_id = f"msg_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO support_messages
                   (message_id, ticket_id, tenant_id, direction, content, author, created_at)
                   VALUES (?,?,?,'inbound',?,?,?)""",
                (msg_rec_id, ticket_id, self.tenant_id,
                 text or f"[{msg_type}]", from_number, now),
            )
        except Exception as exc:
            self._log("WARN", f"Could not create/update ticket: {exc}")

    async def health_check(self) -> Dict[str, Any]:
        try:
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{GRAPH_BASE}/{self._phone_id()}",
                headers={"Authorization": f"Bearer {self._token()}"},
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1),
                    "message": "WhatsApp Business API reachable"}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
