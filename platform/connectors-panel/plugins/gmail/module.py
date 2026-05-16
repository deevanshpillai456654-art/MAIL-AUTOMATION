"""
Gmail OAuth Connector Plugin

Implements OAuthPlugin for Google Gmail API integration.
Handles email reading, sending, and change notification polling.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Optional
from urllib.parse import urlencode

from ...sdk.plugin_sdk import ConnectorSyncResult, OAuthPlugin


class GmailConnector(OAuthPlugin):
    """
    Gmail connector using Google OAuth 2.0 and the Gmail REST API.

    Authentication flow:
    1. Call get_auth_url() to get the Google consent URL
    2. User authenticates; Google redirects to redirect_uri with ?code=...
    3. Call exchange_code() to obtain access + refresh tokens
    4. Tokens are stored encrypted via the OAuth token model

    Data sync:
    - Polls the Gmail API for new messages
    - Publishes email.received events to the event bus
    """

    GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

    @property
    def plugin_id(self) -> str:
        return "gmail_connector"

    @property
    def name(self) -> str:
        return "Gmail"

    @property
    def version(self) -> str:
        return "2.0.1"

    @property
    def category(self) -> str:
        return "communication"

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_client_id(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("client_id") or os.environ.get("GMAIL_CLIENT_ID", "")

    def _get_client_secret(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("client_secret") or os.environ.get("GMAIL_CLIENT_SECRET", "")

    def _get_redirect_uri(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("redirect_uri") or os.environ.get("GMAIL_REDIRECT_URI", "")

    # ------------------------------------------------------------------
    # OAuth flow
    # ------------------------------------------------------------------

    def get_auth_url(self, tenant_id: str, redirect_uri: str) -> str:
        """Build the Google OAuth consent URL."""
        client_id = self._get_client_id()
        if not client_id:
            raise ValueError("GMAIL_CLIENT_ID not configured")

        scopes = " ".join([
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/userinfo.email",
            "openid",
        ])

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scopes,
            "access_type": "offline",
            "prompt": "consent",
            "state": tenant_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, tenant_id: str, code: str) -> dict[str, Any]:
        """Exchange auth code for access + refresh tokens."""
        import httpx
        response = httpx.post(
            self.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self._get_client_id(),
                "client_secret": self._get_client_secret(),
                "redirect_uri": self._get_redirect_uri(),
            },
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    def refresh_token(self, tenant_id: str) -> dict[str, Any]:
        """Refresh the access token using the stored refresh token."""
        stored = self.get_stored_token(tenant_id)
        if not stored or not stored.get("refresh_token"):
            raise ValueError("No refresh token available for this tenant")

        import httpx
        response = httpx.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": stored["refresh_token"],
                "client_id": self._get_client_id(),
                "client_secret": self._get_client_secret(),
            },
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Data sync
    # ------------------------------------------------------------------

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch unread emails from Gmail inbox.
        Returns a list of message dicts with id, subject, from, snippet.
        """
        token = self.get_stored_token(tenant_id)
        if not token:
            self._log("WARN", "No OAuth token for tenant — cannot fetch Gmail data", tenant_id)
            return []

        access_token = token["access_token"]
        query = kwargs.get("query", "is:unread in:inbox")
        max_results = kwargs.get("max_results", 10)

        try:
            import httpx
            # List messages
            list_response = httpx.get(
                f"{self.GMAIL_API_BASE}/users/me/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"q": query, "maxResults": max_results},
                timeout=30.0,
            )
            list_response.raise_for_status()
            messages_raw = list_response.json().get("messages", [])

            # Fetch each message header
            messages: list[dict[str, Any]] = []
            for msg_ref in messages_raw:
                msg_id = msg_ref["id"]
                msg_response = httpx.get(
                    f"{self.GMAIL_API_BASE}/users/me/messages/{msg_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"format": "metadata", "metadataHeaders": ["From", "To", "Subject", "Date"]},
                    timeout=15.0,
                )
                if msg_response.is_success:
                    msg_data = msg_response.json()
                    headers = {
                        h["name"].lower(): h["value"]
                        for h in msg_data.get("payload", {}).get("headers", [])
                    }
                    messages.append({
                        "id": msg_id,
                        "thread_id": msg_data.get("threadId", ""),
                        "snippet": msg_data.get("snippet", ""),
                        "subject": headers.get("subject", "(no subject)"),
                        "from": headers.get("from", ""),
                        "to": headers.get("to", ""),
                        "date": headers.get("date", ""),
                        "label_ids": msg_data.get("labelIds", []),
                    })

            return messages
        except Exception as exc:
            self._log("ERROR", f"Gmail fetch failed: {exc}", tenant_id)
            return []

    def sync(self, tenant_id: str) -> ConnectorSyncResult:
        """Sync new emails and publish email.received events."""
        import asyncio
        import time
        start = time.monotonic()
        result = ConnectorSyncResult(success=False)

        emails = self.fetch_data(tenant_id)
        result.records_processed = len(emails)

        # Publish events
        try:
            from ...shared.event_bus import get_event_bus
            bus = get_event_bus()
            loop = asyncio.new_event_loop()
            for email in emails:
                loop.run_until_complete(
                    bus.publish("email.received", self.plugin_id, tenant_id, email)
                )
            loop.close()
        except Exception as exc:
            result.add_error(f"Event publish failed: {exc}")

        result.success = not result.has_errors
        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        token = self.get_stored_token(tenant_id)
        if not token:
            return False
        try:
            import httpx
            response = httpx.get(
                f"{self.GMAIL_API_BASE}/users/me/profile",
                headers={"Authorization": f"Bearer {token['access_token']}"},
                timeout=10.0,
            )
            return response.is_success
        except Exception:
            return False

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        if not self._get_client_id():
            return {"status": "error", "message": "GMAIL_CLIENT_ID not configured"}

        token = self.get_stored_token(tenant_id)
        if not token:
            return {"status": "degraded", "message": "No OAuth token — authorization required"}

        ok = self.test_connection(tenant_id, {})
        return {
            "status": "ok" if ok else "error",
            "message": "Gmail API reachable" if ok else "Gmail API unreachable — token may be expired",
        }

    # ------------------------------------------------------------------
    # Send email
    # ------------------------------------------------------------------

    def send_email(
        self,
        tenant_id: str,
        to: str,
        subject: str,
        body: str,
        body_html: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send an email via the Gmail API.

        Args:
            tenant_id:  Tenant identifier
            to:         Recipient email address
            subject:    Email subject
            body:       Plain-text body
            body_html:  Optional HTML body

        Returns:
            Gmail API send response dict.
        """
        token = self.get_stored_token(tenant_id)
        if not token:
            raise ValueError("No OAuth token available")

        # Build RFC 2822 message
        if body_html:
            import email.mime.multipart as mp
            import email.mime.text as mt
            msg = mp.MIMEMultipart("alternative")
            msg.attach(mt.MIMEText(body, "plain"))
            msg.attach(mt.MIMEText(body_html, "html"))
        else:
            import email.mime.text as mt
            msg = mt.MIMEText(body, "plain")

        msg["To"] = to
        msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        import httpx
        response = httpx.post(
            f"{self.GMAIL_API_BASE}/users/me/messages/send",
            headers={"Authorization": f"Bearer {token['access_token']}"},
            json={"raw": raw},
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()

        # Publish sent event
        try:
            import asyncio
            from ...shared.event_bus import get_event_bus
            bus = get_event_bus()
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                bus.publish("email.sent", self.plugin_id, tenant_id, {"to": to, "subject": subject, "message_id": result.get("id")})
            )
            loop.close()
        except Exception:
            pass

        return result

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["client_id", "client_secret", "redirect_uri"],
            "properties": {
                "client_id": {"type": "string", "description": "Google OAuth Client ID"},
                "client_secret": {"type": "string", "format": "secret", "description": "Google OAuth Client Secret"},
                "redirect_uri": {"type": "string", "description": "OAuth redirect URI"},
                "poll_interval_seconds": {"type": "integer", "default": 60, "description": "How often to poll for new emails"},
            },
        }

    def get_permissions(self) -> list[str]:
        return ["gmail.read", "gmail.send", "gmail.modify", "contacts.read"]

    def get_events(self) -> list[str]:
        return ["email.received", "email.sent", "email.bounced", "email.opened"]
