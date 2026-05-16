"""
Slack OAuth Connector Plugin

Integrates with the Slack Web API for messaging, notifications,
and channel management. Processes Slack Events API webhooks.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Optional
from urllib.parse import urlencode

from ...sdk.plugin_sdk import ConnectorSyncResult, OAuthPlugin


class SlackConnector(OAuthPlugin):
    """
    Slack connector (OAuth 2.0 + Events API).

    Supports:
    - Sending messages to channels
    - Receiving real-time events via Slack Events API webhooks
    - OAuth v2 with bot scopes
    """

    SLACK_API_BASE = "https://slack.com/api"
    AUTH_URL = "https://slack.com/oauth/v2/authorize"
    TOKEN_URL = f"{SLACK_API_BASE}/oauth.v2.access"

    @property
    def plugin_id(self) -> str:
        return "slack_connector"

    @property
    def name(self) -> str:
        return "Slack"

    @property
    def version(self) -> str:
        return "1.2.0"

    @property
    def category(self) -> str:
        return "communication"

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_client_id(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("client_id") or os.environ.get("SLACK_CLIENT_ID", "")

    def _get_client_secret(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("client_secret") or os.environ.get("SLACK_CLIENT_SECRET", "")

    def _get_signing_secret(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("signing_secret") or os.environ.get("SLACK_SIGNING_SECRET", "")

    def _get_redirect_uri(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("redirect_uri") or os.environ.get("SLACK_REDIRECT_URI", "")

    def _api_headers(self, token: dict) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token['access_token']}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # ------------------------------------------------------------------
    # OAuth flow
    # ------------------------------------------------------------------

    def get_auth_url(self, tenant_id: str, redirect_uri: str) -> str:
        client_id = self._get_client_id()
        if not client_id:
            raise ValueError("SLACK_CLIENT_ID not configured")

        scopes = "channels:read,channels:history,chat:write,chat:write.public,users:read,team:read,incoming-webhook"
        params = {
            "client_id": client_id,
            "scope": scopes,
            "redirect_uri": redirect_uri,
            "state": tenant_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, tenant_id: str, code: str) -> dict[str, Any]:
        import httpx
        response = httpx.post(
            self.TOKEN_URL,
            data={
                "client_id": self._get_client_id(),
                "client_secret": self._get_client_secret(),
                "code": code,
                "redirect_uri": self._get_redirect_uri(),
            },
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise ValueError(f"Slack OAuth error: {data.get('error')}")
        # Normalize to standard token format
        return {
            "access_token": data["access_token"],
            "token_type": "bearer",
            "team": data.get("team", {}),
            "bot_user_id": data.get("bot_user_id"),
            "incoming_webhook": data.get("incoming_webhook", {}),
        }

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def send_message(
        self,
        channel: str,
        text: str,
        tenant_id: str,
        blocks: Optional[list] = None,
        thread_ts: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Send a message to a Slack channel.

        Args:
            channel:   Channel ID or name (e.g. #general or C01234567)
            text:      Message text (used as fallback for blocks)
            tenant_id: Tenant making the request
            blocks:    Optional Slack Block Kit blocks
            thread_ts: Optional thread timestamp to reply in thread

        Returns:
            Slack API response dict.
        """
        token = self.get_stored_token(tenant_id)
        if not token:
            raise ValueError("No OAuth token available for tenant")

        import httpx
        body: dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            body["blocks"] = blocks
        if thread_ts:
            body["thread_ts"] = thread_ts

        response = httpx.post(
            f"{self.SLACK_API_BASE}/chat.postMessage",
            headers=self._api_headers(token),
            json=body,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise ValueError(f"Slack API error: {data.get('error')}")

        # Publish event
        self._publish_event(
            "slack.notification.sent",
            tenant_id,
            {"channel": channel, "text": text, "ts": data.get("ts")},
        )
        return data

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch list of channels the bot is a member of."""
        token = self.get_stored_token(tenant_id)
        if not token:
            return []

        try:
            import httpx
            response = httpx.get(
                f"{self.SLACK_API_BASE}/conversations.list",
                headers=self._api_headers(token),
                params={"types": "public_channel,private_channel", "limit": 100},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                return []
            return data.get("channels", [])
        except Exception as exc:
            self._log("ERROR", f"Slack channels fetch failed: {exc}", tenant_id)
            return []

    # ------------------------------------------------------------------
    # Webhook handling (Slack Events API)
    # ------------------------------------------------------------------

    def handle_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        Process Slack Events API webhook payload.

        Handles:
        - url_verification (challenge)
        - event_callback (message, app_mention, channel_created, etc.)
        """
        # URL verification challenge
        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}

        event_type_raw = payload.get("type", "")
        if event_type_raw != "event_callback":
            return {"processed": False, "reason": f"Unsupported payload type: {event_type_raw}"}

        event = payload.get("event", {})
        slack_event_type = event.get("type", "")

        # Map Slack event types to MailPilot events
        event_map = {
            "message": "slack.message.received",
            "app_mention": "slack.message.received",
            "channel_created": "slack.channel.created",
        }
        mailpilot_event = event_map.get(slack_event_type, "webhook.received")

        event_payload = {
            "slack_event_type": slack_event_type,
            "team_id": payload.get("team_id", ""),
            "event_id": payload.get("event_id", ""),
            "event": event,
        }

        self._publish_event(mailpilot_event, tenant_id, event_payload)
        return {"processed": True, "event_type": mailpilot_event}

    def validate_signature(self, payload: bytes, headers: dict[str, str]) -> bool:
        """Verify Slack signing secret signature."""
        signing_secret = self._get_signing_secret()
        if not signing_secret:
            return True

        timestamp = headers.get("X-Slack-Request-Timestamp") or headers.get("x-slack-request-timestamp", "")
        signature = headers.get("X-Slack-Signature") or headers.get("x-slack-signature", "")

        if not timestamp or not signature:
            return False

        # Replay attack prevention: reject if older than 5 minutes
        if abs(time.time() - int(timestamp)) > 300:
            return False

        sig_basestring = f"v0:{timestamp}:{payload.decode()}"
        expected = "v0=" + hmac.new(
            signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

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
                f"{self.SLACK_API_BASE}/auth.test",
                headers=self._api_headers(token),
                timeout=10.0,
            )
            data = response.json()
            return bool(data.get("ok"))
        except Exception:
            return False

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        if not self._get_client_id():
            return {"status": "error", "message": "SLACK_CLIENT_ID not configured"}
        token = self.get_stored_token(tenant_id)
        if not token:
            return {"status": "degraded", "message": "No OAuth token — authorization required"}
        ok = self.test_connection(tenant_id, {})
        return {"status": "ok" if ok else "error", "message": "Slack API reachable" if ok else "Slack API unreachable"}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _publish_event(self, event_type: str, tenant_id: str, payload: dict) -> None:
        try:
            import asyncio
            from ...shared.event_bus import get_event_bus
            bus = get_event_bus()
            loop = asyncio.new_event_loop()
            loop.run_until_complete(bus.publish(event_type, self.plugin_id, tenant_id, payload))
            loop.close()
        except Exception:
            pass

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["client_id", "client_secret", "redirect_uri"],
            "properties": {
                "client_id": {"type": "string", "description": "Slack App Client ID"},
                "client_secret": {"type": "string", "format": "secret", "description": "Slack App Client Secret"},
                "redirect_uri": {"type": "string", "description": "OAuth redirect URI"},
                "signing_secret": {"type": "string", "format": "secret", "description": "Slack App Signing Secret for webhook verification"},
            },
        }

    def get_permissions(self) -> list[str]:
        return ["slack.message.send", "slack.channels.read", "slack.users.read"]

    def get_events(self) -> list[str]:
        return ["slack.message.received", "slack.notification.sent", "slack.channel.created"]
