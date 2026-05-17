"""Slack Enterprise Connector — OAuth2, messaging, alerts, approval workflows."""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import ConnectorManifest, OAuthConfig, WebhookConfig, SyncConfig, Permission

MANIFEST = ConnectorManifest(
    id="slack_enterprise",
    name="Slack",
    category="communication",
    description="Send alerts, notifications, and approval workflows via Slack.",
    version="1.0.0",
    icon="💬",
    supports_oauth=True,
    supports_webhook=True,
    oauth=OAuthConfig(
        provider_id="slack",
        auth_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=["channels:read", "chat:write", "incoming-webhook",
                "users:read", "files:write", "commands"],
        supports_refresh=False,
        extra_params={"user_scope": ""},
    ),
    webhook=WebhookConfig(
        events=["message", "app_mention", "reaction_added",
                "workflow_step_execute", "interactive_message"],
        signature_header="X-Slack-Signature",
    ),
    sync=SyncConfig(entities=["channels", "users"], default_interval_seconds=86400),
    permissions=[
        Permission("channels:read", "Channels", "List public channels"),
        Permission("chat:write", "Messages", "Send messages"),
        Permission("users:read", "Users", "Read user list"),
    ],
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
        "signing_secret": {"type": "string", "required": True, "secret": True,
                           "description": "Slack signing secret for webhook verification"},
        "default_channel": {"type": "string", "default": "#general",
                             "description": "Default channel for notifications"},
    },
    emits_events=["slack.message.received", "slack.approval.completed"],
)

SLACK_API = "https://slack.com/api"


class SlackEnterpriseConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 1.0   # Slack Tier 1: 1 request/sec for most methods
    RATE_BURST = 5.0

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = urlencode({
            "client_id": self.config["client_id"],
            "scope": ",".join(MANIFEST.oauth.scopes),
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"https://slack.com/oauth/v2/authorize?{params}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        resp = await client.post(
            f"{SLACK_API}/oauth.v2.access",
            data={
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack OAuth error: {data.get('error')}")

        access_token = data.get("access_token", "")
        bot_token = data.get("bot", {}).get("bot_access_token", access_token)
        from datetime import timedelta
        # Slack tokens don't expire, use far-future expiry
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(days=3650)).isoformat()
        self._store_token(bot_token, None, expires_at,
                          MANIFEST.oauth.scopes)
        return data

    async def refresh_access_token(self) -> str:
        tok = self._get_token()
        if tok:
            return tok["access_token"]
        raise RuntimeError("No Slack token available")

    def _auth_header(self, token: str) -> Dict:
        return {"Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8"}

    async def _api_call(self, method: str, payload: Dict) -> Dict:
        token = await self.get_valid_token()
        client = self._get_http()
        resp = await client.post(
            f"{SLACK_API}/{method}",
            headers=self._auth_header(token),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error ({method}): {data.get('error')}")
        return data

    async def send_message(self, channel: str, text: str,
                            blocks: Optional[List] = None) -> Dict:
        payload: Dict[str, Any] = {"channel": channel, "text": text}
        if blocks:
            payload["blocks"] = blocks
        return await self._api_call("chat.postMessage", payload)

    async def send_alert(self, title: str, message: str, level: str = "info",
                          channel: Optional[str] = None) -> Dict:
        color_map = {"info": "#2563EB", "warning": "#F59E0B",
                     "error": "#EF4444", "success": "#10B981"}
        color = color_map.get(level, "#64748B")
        ch = channel or self.config.get("default_channel", "#general")
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn",
                     "text": f"*Level:* {level.upper()} | *Time:* {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"}
                ],
            },
        ]
        return await self.send_message(ch, title, blocks)

    async def send_approval_request(self, channel: str, title: str,
                                     description: str, callback_id: str,
                                     metadata: Optional[Dict] = None) -> Dict:
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{title}*\n{description}"},
            },
            {
                "type": "actions",
                "block_id": callback_id,
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "value": "approve",
                        "action_id": f"{callback_id}_approve",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": "reject",
                        "action_id": f"{callback_id}_reject",
                    },
                ],
            },
        ]
        result = await self.send_message(channel, title, blocks)
        self._publish_event("slack.approval.requested",
                            {"callback_id": callback_id, "title": title,
                             "metadata": metadata or {}})
        return result

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "channels":
            token = await self.get_valid_token()
            client = self._get_http()
            cursor = None
            channels = []
            while True:
                params: Dict[str, Any] = {"types": "public_channel,private_channel",
                                           "limit": 200}
                if cursor:
                    params["cursor"] = cursor
                resp = await client.get(
                    f"{SLACK_API}/conversations.list",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                channels.extend(data.get("channels", []))
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
            return {"synced": len(channels), "entity": "channels"}

        elif entity == "users":
            token = await self.get_valid_token()
            client = self._get_http()
            resp = await client.get(
                f"{SLACK_API}/users.list",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 200},
            )
            resp.raise_for_status()
            data = resp.json()
            users = data.get("members", [])
            return {"synced": len(users), "entity": "users"}

        return {"synced": 0, "entity": entity}

    async def verify_webhook_signature(self, raw_body: bytes,
                                        headers: Dict) -> bool:
        signing_secret = self.config.get("signing_secret", "")
        if not signing_secret:
            return False  # fail-closed: configure signing_secret to enable Slack webhooks
        timestamp = headers.get("x-slack-request-timestamp", "")
        sig_header = headers.get("x-slack-signature", "")
        if not timestamp or not sig_header:
            return False
        # Replay attack guard: reject requests older than 5 minutes
        if abs(time.time() - float(timestamp)) > 300:
            return False
        base_str = f"v0:{timestamp}:{raw_body.decode('utf-8', errors='replace')}"
        expected = "v0=" + hmac.new(
            signing_secret.encode(), base_str.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                              raw_body: bytes, headers: Dict) -> None:
        # URL verification challenge
        if payload.get("type") == "url_verification":
            return

        outer_type = payload.get("type", "")

        # Interactive components (button clicks, modal submissions)
        if outer_type == "block_actions":
            for action in payload.get("actions", []):
                action_id = action.get("action_id", "")
                value = action.get("value", "")
                self._publish_event("slack.approval.completed",
                                    {"action_id": action_id, "value": value,
                                     "user": payload.get("user", {}).get("id"),
                                     "source": "slack"})
            return

        # Event API
        if outer_type == "event_callback":
            event = payload.get("event", {})
            ev_type = event.get("type", "")
            if ev_type == "message" and not event.get("bot_id"):
                self._publish_event("slack.message.received",
                                    {"channel": event.get("channel"),
                                     "user": event.get("user"),
                                     "text": event.get("text", ""),
                                     "ts": event.get("ts")})
            elif ev_type == "app_mention":
                self._publish_event("slack.mention.received",
                                    {"channel": event.get("channel"),
                                     "user": event.get("user"),
                                     "text": event.get("text", "")})

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.post(
                f"{SLACK_API}/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
            latency = (time.monotonic() - t0) * 1000
            data = resp.json()
            ok = data.get("ok", False)
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1),
                    "team": data.get("team"), "bot_id": data.get("bot_id")}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
