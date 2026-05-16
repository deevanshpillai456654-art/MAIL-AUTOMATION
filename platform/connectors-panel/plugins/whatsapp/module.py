"""
WhatsApp Business API Connector Plugin

Implements WebhookPlugin to handle inbound WhatsApp messages and status updates.
Publishes events to the MailPilot event bus.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Optional

from ...sdk.plugin_sdk import ConnectorSyncResult, WebhookPlugin


class WhatsAppConnector(WebhookPlugin):
    """
    WhatsApp Business API connector.

    Handles:
    - Inbound messages via Meta webhook
    - Webhook verification (hub challenge)
    - HMAC-SHA256 signature verification
    - Publishes whatsapp.* events to the event bus
    """

    WHATSAPP_API_BASE = "https://graph.facebook.com/v17.0"

    @property
    def plugin_id(self) -> str:
        return "whatsapp_connector"

    @property
    def name(self) -> str:
        return "WhatsApp Business"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "communication"

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_api_key(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("api_key") or os.environ.get("WHATSAPP_API_KEY", "")

    def _get_phone_number_id(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("phone_number_id") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")

    def _get_verify_token(self) -> str:
        return os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_install(self, tenant_id: str, config: dict[str, Any]) -> bool:
        if not config.get("api_key") and not os.environ.get("WHATSAPP_API_KEY"):
            self._log("WARN", "WhatsApp API key not configured", tenant_id)
        self._log("INFO", "WhatsApp connector installed", tenant_id)
        return True

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        api_key = self._get_api_key()
        if not api_key:
            return {"status": "error", "message": "WHATSAPP_API_KEY not configured"}

        try:
            import httpx
            response = httpx.get(
                f"{self.WHATSAPP_API_BASE}/me",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            if response.is_success:
                return {"status": "ok", "message": "WhatsApp API reachable"}
            return {"status": "degraded", "message": f"API returned {response.status_code}"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Webhook signature validation
    # ------------------------------------------------------------------

    def validate_signature(self, payload: bytes, headers: dict[str, str]) -> bool:
        """
        Validate inbound webhook using HMAC-SHA256 with the app secret.
        Meta sends the signature in the X-Hub-Signature-256 header.
        """
        app_secret = os.environ.get("WHATSAPP_APP_SECRET", "")
        if not app_secret:
            # No secret configured — accept all (not recommended for production)
            return True

        signature_header = (
            headers.get("X-Hub-Signature-256")
            or headers.get("x-hub-signature-256")
            or ""
        )
        if not signature_header:
            return False

        expected = "sha256=" + hmac.new(
            app_secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    # ------------------------------------------------------------------
    # Webhook handler
    # ------------------------------------------------------------------

    def handle_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        Parse and process a WhatsApp Business API webhook payload.

        Handles:
        - messages (text, media, location, contacts, interactive)
        - statuses (sent, delivered, read, failed)
        - account-level notifications
        """
        object_type = payload.get("object", "")
        if object_type not in ("whatsapp_business_account",):
            return {"processed": False, "reason": f"Unknown object type: {object_type}"}

        events_published = 0
        message_ids: list[str] = []

        entry_list = payload.get("entry", [])
        for entry in entry_list:
            waba_id = entry.get("id", "")
            changes = entry.get("changes", [])

            for change in changes:
                field = change.get("field", "")
                value = change.get("value", {})

                if field == "messages":
                    result = self._process_messages(value, tenant_id)
                    events_published += result["events_published"]
                    message_ids.extend(result.get("message_ids", []))

                elif field == "message_deliveries" or field == "statuses":
                    result = self._process_statuses(value, tenant_id)
                    events_published += result["events_published"]

        return {
            "processed": True,
            "events_published": events_published,
            "message_ids": message_ids,
        }

    def _process_messages(self, value: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        """Process inbound messages from the webhook value object."""
        import asyncio
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        metadata = value.get("metadata", {})
        events_published = 0
        message_ids = []

        contact_map: dict[str, dict] = {}
        for c in contacts:
            wa_id = c.get("wa_id", "")
            if wa_id:
                contact_map[wa_id] = c.get("profile", {})

        for msg in messages:
            msg_id = msg.get("id", "")
            from_number = msg.get("from", "")
            msg_type = msg.get("type", "text")
            timestamp = msg.get("timestamp", "")

            event_payload = {
                "message_id": msg_id,
                "from": from_number,
                "to": metadata.get("phone_number_id", ""),
                "type": msg_type,
                "timestamp": timestamp,
                "profile": contact_map.get(from_number, {}),
            }

            # Extract message content by type
            if msg_type == "text":
                event_payload["text"] = msg.get("text", {}).get("body", "")
            elif msg_type in ("image", "video", "audio", "document", "sticker"):
                event_payload["media"] = msg.get(msg_type, {})
            elif msg_type == "location":
                event_payload["location"] = msg.get("location", {})
            elif msg_type == "contacts":
                event_payload["contacts"] = msg.get("contacts", [])
            elif msg_type == "interactive":
                event_payload["interactive"] = msg.get("interactive", {})
            elif msg_type == "button":
                event_payload["button"] = msg.get("button", {})

            # Publish event
            try:
                bus_module = __import__(
                    "platform.connectors_panel.shared.event_bus",
                    fromlist=["get_event_bus"],
                )
                bus = bus_module.get_event_bus()
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    bus.publish("whatsapp.message.received", self.plugin_id, tenant_id, event_payload)
                )
                loop.close()
            except Exception:
                pass

            message_ids.append(msg_id)
            events_published += 1

        return {"events_published": events_published, "message_ids": message_ids}

    def _process_statuses(self, value: dict[str, Any], tenant_id: str) -> dict[str, Any]:
        """Process message status updates."""
        import asyncio
        statuses = value.get("statuses", [])
        events_published = 0

        for status_update in statuses:
            event_payload = {
                "message_id": status_update.get("id", ""),
                "recipient": status_update.get("recipient_id", ""),
                "status": status_update.get("status", ""),
                "timestamp": status_update.get("timestamp", ""),
                "conversation": status_update.get("conversation", {}),
                "pricing": status_update.get("pricing", {}),
            }
            try:
                bus_module = __import__(
                    "platform.connectors_panel.shared.event_bus",
                    fromlist=["get_event_bus"],
                )
                bus = bus_module.get_event_bus()
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    bus.publish("whatsapp.status.updated", self.plugin_id, tenant_id, event_payload)
                )
                loop.close()
                events_published += 1
            except Exception:
                pass

        return {"events_published": events_published}

    # ------------------------------------------------------------------
    # Data fetch — retrieve recent messages from the API
    # ------------------------------------------------------------------

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch recent messages from the WhatsApp Business API.
        Returns a list of message objects in the Meta Graph API format.
        """
        api_key = self._get_api_key()
        phone_number_id = self._get_phone_number_id()

        if not api_key or not phone_number_id:
            self._log("WARN", "WhatsApp credentials not configured", tenant_id)
            return []

        try:
            import httpx
            response = httpx.get(
                f"{self.WHATSAPP_API_BASE}/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"limit": kwargs.get("limit", 25)},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as exc:
            self._log("ERROR", f"Failed to fetch WhatsApp messages: {exc}", tenant_id)
            return []

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        api_key = self._get_api_key(config)
        if not api_key:
            return False
        try:
            import httpx
            response = httpx.get(
                f"{self.WHATSAPP_API_BASE}/me",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            return response.is_success
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Send message (utility method, not part of the SDK interface)
    # ------------------------------------------------------------------

    def send_message(
        self,
        to: str,
        message: str,
        tenant_id: str,
        config: Optional[dict] = None,
    ) -> dict[str, Any]:
        """
        Send a WhatsApp text message.

        Args:
            to:        Recipient phone number (E.164 format, e.g. +1234567890)
            message:   Text message content
            tenant_id: Tenant making the request
            config:    Optional config override (api_key, phone_number_id)

        Returns:
            Meta API response dict with message_id on success.
        """
        api_key = self._get_api_key(config)
        phone_number_id = self._get_phone_number_id(config)

        if not api_key or not phone_number_id:
            raise ValueError("WhatsApp API key and phone_number_id are required")

        import httpx
        response = httpx.post(
            f"{self.WHATSAPP_API_BASE}/{phone_number_id}/messages",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": message},
            },
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
                bus.publish(
                    "whatsapp.message.sent",
                    self.plugin_id,
                    tenant_id,
                    {"to": to, "message": message, "response": result},
                )
            )
            loop.close()
        except Exception:
            pass

        return result

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["phone_number_id", "whatsapp_business_account_id", "api_key"],
            "properties": {
                "phone_number_id": {
                    "type": "string",
                    "description": "WhatsApp Business phone number ID from Meta Developer Console",
                },
                "whatsapp_business_account_id": {
                    "type": "string",
                    "description": "WhatsApp Business Account (WABA) ID",
                },
                "api_key": {
                    "type": "string",
                    "format": "secret",
                    "description": "Meta System User Access Token",
                },
                "webhook_verify_token": {
                    "type": "string",
                    "format": "secret",
                    "description": "Custom verify token for webhook subscription verification",
                },
            },
        }

    def get_permissions(self) -> list[str]:
        return ["messages.read", "messages.send", "contacts.read"]

    def get_events(self) -> list[str]:
        return ["whatsapp.message.received", "whatsapp.message.sent", "whatsapp.status.updated"]
