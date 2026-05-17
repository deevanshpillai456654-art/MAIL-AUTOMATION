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
        "pubsub_audience": {"type": "string", "default": "", "description": "Expected Pub/Sub push subscription URL for JWT audience verification"},
    },
    emits_events=[
        "email.received", "email.sent", "email.bounced",
        "ai.classification.completed", "ocr.document.processed",
    ],
)

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1"
OAUTH_BASE = "https://oauth2.googleapis.com"
_GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
_JWKS_CACHE: Dict[str, Any] = {}  # {kid: jwk}
_JWKS_CACHED_AT: float = 0.0
_JWKS_TTL = 3600.0  # refresh at most once per hour


async def _get_google_jwk(http_client, kid: str) -> Optional[Dict[str, Any]]:
    """Return the JWK matching `kid` from Google's JWKS; module-level cached."""
    global _JWKS_CACHED_AT
    import time as _time
    now = _time.monotonic()
    if now - _JWKS_CACHED_AT > _JWKS_TTL:
        try:
            resp = await http_client.get(_GOOGLE_JWKS_URI)
            if resp.status_code == 200:
                keys = resp.json().get("keys", [])
                _JWKS_CACHE.clear()
                for k in keys:
                    _JWKS_CACHE[k.get("kid", "")] = k
                _JWKS_CACHED_AT = now
        except Exception:
            pass  # use stale cache on network failure; key lookup below handles miss
    return _JWKS_CACHE.get(kid)


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
                "SELECT id FROM crm_contacts WHERE email=? AND tenant_id=?",
                (email_addr, self.tenant_id),
            )
            if contact:
                self._publish_event("crm.activity.email",
                                    {"contact_id": contact["id"],
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
        """
        Verify Google Pub/Sub JWT push notification.

        Google signs each push message with a JWT in Authorization: Bearer.
        We verify the RSA-SHA256 signature against Google's JWKS and check
        standard claims (exp, iss, optional aud).
        """
        import base64 as _b64
        import json as _json
        import time as _time

        auth = headers.get("authorization", "") or headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        jwt_token = auth[len("Bearer "):]

        try:
            parts = jwt_token.split(".")
            if len(parts) != 3:
                return False
            header_b64, payload_b64, sig_b64 = parts

            def _decode_b64url(s: str) -> bytes:
                rem = len(s) % 4
                if rem:
                    s += "=" * (4 - rem)
                return _b64.urlsafe_b64decode(s)

            header = _json.loads(_decode_b64url(header_b64))
            if header.get("alg") != "RS256":
                return False
            kid = header.get("kid", "")

            payload = _json.loads(_decode_b64url(payload_b64))

            # Reject expired tokens
            if _time.time() > payload.get("exp", 0):
                return False

            # Verify issuer
            if payload.get("iss", "") not in (
                "accounts.google.com", "https://accounts.google.com"
            ):
                return False

            # Optional audience check — set pubsub_audience in connector config
            audience = self.config.get("pubsub_audience", "")
            if audience:
                aud = payload.get("aud", "")
                token_auds = aud if isinstance(aud, list) else [aud]
                if audience not in token_auds:
                    return False

            # Fetch Google JWKS (cached at module level to avoid per-request calls)
            jwk = await _get_google_jwk(self._get_http(), kid)
            if not jwk:
                return False

            # Build RSA public key from JWK components
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.asymmetric import padding as _pad
            from cryptography.hazmat.primitives import hashes as _hashes

            def _big_int(b64url: str) -> int:
                return int.from_bytes(_decode_b64url(b64url), "big")

            pub_key = RSAPublicNumbers(
                _big_int(jwk["e"]), _big_int(jwk["n"])
            ).public_key(default_backend())

            sig = _decode_b64url(sig_b64)
            message = f"{header_b64}.{payload_b64}".encode("ascii")
            pub_key.verify(sig, message, _pad.PKCS1v15(), _hashes.SHA256())
            return True

        except Exception:
            return False

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
