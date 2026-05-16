"""Microsoft Teams Connector — OAuth2 (MSAL), Graph API, notifications, approvals."""
from __future__ import annotations

import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import ConnectorManifest, OAuthConfig, SyncConfig, Permission

MANIFEST = ConnectorManifest(
    id="teams",
    name="Microsoft Teams",
    category="communication",
    description="Send notifications and approval workflows via Microsoft Teams.",
    version="1.0.0",
    icon="🔷",
    supports_oauth=True,
    oauth=OAuthConfig(
        provider_id="microsoft",
        auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scopes=["https://graph.microsoft.com/ChannelMessage.Send",
                "https://graph.microsoft.com/Channel.ReadBasic.All",
                "https://graph.microsoft.com/Team.ReadBasic.All",
                "https://graph.microsoft.com/User.Read",
                "offline_access"],
        supports_refresh=True,
        extra_params={"response_type": "code"},
    ),
    sync=SyncConfig(entities=["teams", "channels", "users"],
                    default_interval_seconds=86400),
    permissions=[
        Permission("ChannelMessage.Send", "Messages", "Send channel messages"),
        Permission("Team.ReadBasic.All", "Teams", "List teams"),
        Permission("User.Read", "Profile", "Read user profile"),
    ],
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
        "tenant_id": {"type": "string", "default": "common",
                       "description": "Azure AD tenant ID or 'common'"},
        "default_team_id": {"type": "string", "required": False,
                             "description": "Default Teams team ID for notifications"},
        "default_channel_id": {"type": "string", "required": False,
                                "description": "Default channel ID"},
    },
    emits_events=["teams.message.sent", "teams.approval.completed"],
)

GRAPH_API = "https://graph.microsoft.com/v1.0"


class TeamsConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 2.0
    RATE_BURST = 10.0

    def _token_url(self) -> str:
        tenant = self.config.get("tenant_id", "common")
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def _auth_url(self) -> str:
        tenant = self.config.get("tenant_id", "common")
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = urlencode({
            "client_id": self.config["client_id"],
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(MANIFEST.oauth.scopes),
            "state": state,
        })
        return f"{self._auth_url()}?{params}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        resp = await client.post(
            self._token_url(),
            data={
                "grant_type": "authorization_code",
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "code": code,
                "redirect_uri": redirect_uri,
                "scope": " ".join(MANIFEST.oauth.scopes),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(
            data["access_token"],
            data.get("refresh_token"),
            expires_at,
            data.get("scope", "").split(),
        )
        return data

    async def refresh_access_token(self) -> str:
        tok = self._get_token()
        if not tok or not tok.get("refresh_token"):
            raise RuntimeError("No refresh token")
        client = self._get_http()
        resp = await client.post(
            self._token_url(),
            data={
                "grant_type": "refresh_token",
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "refresh_token": tok["refresh_token"],
                "scope": " ".join(MANIFEST.oauth.scopes),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(
            data["access_token"],
            data.get("refresh_token", tok["refresh_token"]),
            expires_at,
            tok.get("scopes", []),
        )
        return data["access_token"]

    async def _graph_get(self, path: str, params: Optional[Dict] = None) -> Any:
        token = await self.get_valid_token()
        client = self._get_http()
        resp = await client.get(
            f"{GRAPH_API}/{path}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/json"},
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    async def _graph_post(self, path: str, payload: Dict) -> Any:
        token = await self.get_valid_token()
        client = self._get_http()
        resp = await client.post(
            f"{GRAPH_API}/{path}",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def send_channel_message(self, team_id: str, channel_id: str,
                                    content: str, content_type: str = "html") -> Dict:
        result = await self._graph_post(
            f"teams/{team_id}/channels/{channel_id}/messages",
            {"body": {"contentType": content_type, "content": content}},
        )
        self._publish_event("teams.message.sent",
                            {"team_id": team_id, "channel_id": channel_id})
        return result

    async def send_notification(self, title: str, message: str,
                                  level: str = "info") -> Dict:
        team_id = self.config.get("default_team_id", "")
        channel_id = self.config.get("default_channel_id", "")
        if not team_id or not channel_id:
            raise RuntimeError("default_team_id and default_channel_id must be configured")

        color_map = {"info": "#2563EB", "warning": "#F59E0B",
                     "error": "#EF4444", "success": "#10B981"}
        color = color_map.get(level, "#64748B")
        html = (
            f'<div><h3 style="color:{color}">{title}</h3>'
            f'<p>{message}</p>'
            f'<p><em>{datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</em></p></div>'
        )
        return await self.send_channel_message(team_id, channel_id, html)

    async def send_adaptive_card(self, team_id: str, channel_id: str,
                                   card: Dict) -> Dict:
        payload = {
            "body": {
                "contentType": "html",
                "content": "<attachment id='card'></attachment>",
            },
            "attachments": [
                {
                    "id": "card",
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": card,
                }
            ],
        }
        return await self._graph_post(
            f"teams/{team_id}/channels/{channel_id}/messages", payload
        )

    async def send_approval_card(self, team_id: str, channel_id: str,
                                   title: str, description: str,
                                   callback_url: str) -> Dict:
        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "size": "Large", "weight": "Bolder",
                 "text": title},
                {"type": "TextBlock", "text": description, "wrap": True},
            ],
            "actions": [
                {"type": "Action.OpenUrl", "title": "Approve",
                 "url": f"{callback_url}?action=approve"},
                {"type": "Action.OpenUrl", "title": "Reject",
                 "url": f"{callback_url}?action=reject"},
            ],
        }
        result = await self.send_adaptive_card(team_id, channel_id, card)
        self._publish_event("teams.approval.requested",
                            {"title": title, "team_id": team_id,
                             "channel_id": channel_id})
        return result

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "teams":
            data = await self._graph_get("me/joinedTeams")
            teams = data.get("value", [])
            return {"synced": len(teams), "entity": "teams"}

        elif entity == "channels":
            team_id = self.config.get("default_team_id", "")
            if not team_id:
                return {"synced": 0, "entity": "channels", "error": "No default_team_id"}
            data = await self._graph_get(f"teams/{team_id}/channels")
            channels = data.get("value", [])
            return {"synced": len(channels), "entity": "channels"}

        elif entity == "users":
            data = await self._graph_get("users", {"$top": 100,
                                                     "$select": "id,displayName,mail"})
            users = data.get("value", [])
            return {"synced": len(users), "entity": "users"}

        return {"synced": 0, "entity": entity}

    async def verify_webhook_signature(self, raw_body: bytes,
                                        headers: Dict) -> bool:
        # Teams webhook uses HMAC or simple auth token in header
        auth_header = headers.get("authorization", "")
        expected_token = self.config.get("webhook_token", "")
        if expected_token and auth_header:
            return hmac.compare_digest(auth_header, f"Bearer {expected_token}")
        return True

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                              raw_body: bytes, headers: Dict) -> None:
        activity_type = payload.get("type", "")
        if activity_type == "invoke":
            # Adaptive card action response
            value = payload.get("value", {})
            action = value.get("action", "")
            self._publish_event("teams.approval.completed",
                                {"action": action, "payload": value,
                                 "from": payload.get("from", {}).get("id"),
                                 "source": "teams"})
        elif activity_type == "message":
            self._publish_event("teams.message.received",
                                {"text": payload.get("text", ""),
                                 "from": payload.get("from", {}).get("id"),
                                 "channel_id": payload.get("channelData",
                                                            {}).get("channel",
                                                                    {}).get("id")})

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{GRAPH_API}/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            self._record_health(ok, latency)
            data = resp.json() if ok else {}
            return {"healthy": ok, "latency_ms": round(latency, 1),
                    "user": data.get("displayName")}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
