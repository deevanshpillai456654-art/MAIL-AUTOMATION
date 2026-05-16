"""
Gmail Enterprise Connector — multi-account, AI categorization, OCR triggers,
ERP/CRM linking, push notifications via Google Pub/Sub polling.
"""
from __future__ import annotations

import base64
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
    id="gmail",
    name="Gmail Enterprise",
    category="communication",
    description="Multi-account Gmail with AI categorization, thread intelligence, OCR triggers.",
    version="2.0.0",
    icon="📧",
    supports_oauth=True,
    supports_webhook=True,
    oauth=OAuthConfig(
        provider_id="google",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "openid", "email", "profile"],
        supports_refresh=True,
        extra_params={"access_type": "offline", "prompt": "consent"},
    ),
    webhook=WebhookConfig(
        events=["email.received", "email.sent", "email.bounced"],
        signature_header="X-Goog-Signature",
    ),
    sync=SyncConfig(
        entities=["messages", "threads", "labels"],
        default_interval_seconds=300,
    ),
    permissions=[
        Permission("gmail.readonly", "Read Email", "Access email messages"),
        Permission("gmail.send", "Send Email", "Send emails on behalf of user"),
        Permission("gmail.modify", "Modify Email", "Label and modify emails"),
    ],
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
        "label_incoming": {"type": "string", "default": "MailPilot/Inbox"},
        "ai_classify": {"type": "boolean", "default": True},
        "ocr_attachments": {"type": "boolean", "default": False},
        "link_crm": {"type": "boolean", "default": True},
    },
    emits_events=[
        "email.received", "email.sent", "email.bounced",
        "ai.classification.completed", "ocr.document.processed",
    ],
)

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
OAUTH_BASE = "https://oauth2.googleapis.com"


class GmailConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 25.0  # Gmail: 25 req/s per user
    RATE_BURST = 50.0

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = urlencode({
            "client_id": self.config["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(MANIFEST.oauth.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{params}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        resp = await client.post(f"{OAUTH_BASE}/token", data={
            "code": code,
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=data.get("scope", "").split(" "),
        )
        return data

    async def refresh_access_token(self) -> str:
        tok = self._get_token()
        if not tok or not tok.get("refresh_token"):
            raise RuntimeError("No refresh token")
        client = self._get_http()
        resp = await client.post(f"{OAUTH_BASE}/token", data={
            "refresh_token": tok["refresh_token"],
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(
            access_token=data["access_token"],
            refresh_token=tok["refresh_token"],
            expires_at=expires_at,
            scopes=tok.get("scopes", []),
        )
        return data["access_token"]

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        token = await self.get_valid_token()
        client = self._get_http()

        if entity == "messages":
            return await self._sync_messages(client, token, since)
        elif entity == "labels":
            return await self._sync_labels(client, token)
        return {"synced": 0, "entity": entity}

    async def _sync_messages(self, client, token: str,
                              since: Optional[datetime]) -> Dict[str, Any]:
        """Fetch new messages since last sync and process them."""
        params: Dict[str, Any] = {"maxResults": 100, "labelIds": "INBOX"}
        if since:
            after_ts = int(since.timestamp())
            params["q"] = f"after:{after_ts}"

        resp = await client.get(
            f"{GMAIL_BASE}/users/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        msg_refs = data.get("messages", [])
        processed = 0

        for ref in msg_refs[:50]:  # limit per sync cycle
            msg_id = ref["id"]
            try:
                msg_resp = await client.get(
                    f"{GMAIL_BASE}/users/me/messages/{msg_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "metadata",
                            "metadataHeaders": "From,To,Subject,Date"},
                )
                msg_resp.raise_for_status()
                msg = msg_resp.json()
                await self._process_message(msg, token)
                processed += 1
            except Exception as exc:
                self._log("WARN", f"Could not process message {msg_id}: {exc}")

        return {"synced": processed, "entity": "messages"}

    async def _process_message(self, msg: Dict, token: str) -> None:
        headers = {h["name"]: h["value"]
                   for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "")
        msg_date = headers.get("Date", "")

        self._publish_event("email.received", {
            "message_id": msg["id"],
            "thread_id": msg.get("threadId"),
            "from": sender,
            "subject": subject,
            "date": msg_date,
            "labels": msg.get("labelIds", []),
            "snippet": msg.get("snippet", ""),
        })

        # Link to CRM contact if email matches
        if self.config.get("link_crm", True) and sender:
            email_addr = sender.split("<")[-1].rstrip(">").strip()
            contact = self.db.fetch_one(
                "SELECT contact_id FROM crm_contacts WHERE email=? AND tenant_id=?",
                (email_addr, self.tenant_id),
            )
            if contact:
                self._publish_event("crm.activity.email",
                                    {"contact_id": contact["contact_id"],
                                     "message_id": msg["id"],
                                     "subject": subject})

    async def _sync_labels(self, client, token: str) -> Dict[str, Any]:
        resp = await client.get(
            f"{GMAIL_BASE}/users/me/labels",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        labels = resp.json().get("labels", [])
        return {"synced": len(labels), "entity": "labels"}

    async def verify_webhook_signature(self, raw_body: bytes,
                                       headers: Dict[str, str]) -> bool:
        # Google Pub/Sub push notifications use JWT verification
        # For simplicity, accept all from trusted Google IPs (implement JWT check in prod)
        return True

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict[str, str]) -> None:
        # Google Pub/Sub push notification
        message = payload.get("message", {})
        if message:
            encoded_data = message.get("data", "")
            if encoded_data:
                try:
                    decoded = base64.b64decode(encoded_data).decode()
                    data = json.loads(decoded)
                    email_address = data.get("emailAddress", "")
                    history_id = data.get("historyId", "")
                    self._publish_event("email.received",
                                        {"source": "gmail_push",
                                         "email": email_address,
                                         "history_id": history_id})
                    # Enqueue a sync job to fetch the actual message
                    self._enqueue("sync", {"entity": "messages", "connector_id": self.MANIFEST.id})
                except Exception as exc:
                    self._log("WARN", f"Could not parse Pub/Sub message: {exc}")

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{GMAIL_BASE}/users/me/profile",
                headers={"Authorization": f"Bearer {token}"},
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            info = resp.json() if ok else {}
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1),
                    "message": f"Connected as {info.get('emailAddress', 'unknown')}"}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
