"""
Generic Webhook Listener Plugin

Receives arbitrary inbound HTTP webhooks, optionally verifies HMAC signatures,
and routes the payloads to the MailPilot event bus.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Optional

from ...sdk.plugin_sdk import ConnectorPlugin, WebhookPlugin


class WebhookListenerPlugin(WebhookPlugin):
    """
    Generic webhook listener.

    Accepts webhooks from any HTTP source, validates optional HMAC signatures,
    and publishes events to the internal event bus for downstream processing.
    """

    @property
    def plugin_id(self) -> str:
        return "webhook_listener"

    @property
    def name(self) -> str:
        return "Generic Webhook Listener"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "webhook"

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_secret(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("secret") or os.environ.get("WEBHOOK_LISTENER_SECRET", "")

    def _get_event_type_header(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("event_type_header", "X-Webhook-Event")

    def _should_verify_signature(self, config: Optional[dict] = None) -> bool:
        return bool((config or {}).get("verify_signature", True))

    def _get_allowed_ips(self, config: Optional[dict] = None) -> list[str]:
        return (config or {}).get("allowed_ips", []) or []

    # ------------------------------------------------------------------
    # Signature validation
    # ------------------------------------------------------------------

    def validate_signature(self, payload: bytes, headers: dict[str, str]) -> bool:
        """
        Validate webhook HMAC-SHA256 signature.
        Looks for signature in X-Hub-Signature-256 header.
        Returns True if no secret is configured (permissive mode).
        """
        secret = self._get_secret()
        if not secret:
            return True  # No secret = accept all

        # Support multiple signature header formats
        signature = (
            headers.get("X-Hub-Signature-256")
            or headers.get("x-hub-signature-256")
            or headers.get("X-Signature")
            or headers.get("x-signature")
            or ""
        )

        if not signature:
            return False

        from ...shared.utils import verify_hmac
        return verify_hmac(secret, payload, signature)

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
        Process an inbound webhook payload.

        Determines the event type from:
        1. X-Webhook-Event header (or configured event_type_header)
        2. Falls back to "webhook.received"

        Publishes the event to the MailPilot event bus.
        """
        event_type_header = self._get_event_type_header()
        # Header lookup is case-insensitive
        headers_lower = {k.lower(): v for k, v in headers.items()}
        event_type = (
            headers_lower.get(event_type_header.lower())
            or headers_lower.get("x-webhook-event")
            or headers_lower.get("x-event-type")
            or "webhook.received"
        )

        # Enrich payload with metadata
        enriched_payload = {
            "event_type": event_type,
            "payload": payload,
            "headers": {
                k: v for k, v in headers.items()
                # Exclude sensitive headers
                if k.lower() not in ("authorization", "x-hub-signature-256", "x-signature")
            },
        }

        try:
            import asyncio
            from ...shared.event_bus import get_event_bus
            bus = get_event_bus()
            loop = asyncio.new_event_loop()
            event_id = loop.run_until_complete(
                bus.publish(event_type, self.plugin_id, tenant_id, enriched_payload)
            )
            loop.close()

            self._log("INFO", f"Webhook received: {event_type}", tenant_id, {"event_id": event_id})
            return {"processed": True, "event_type": event_type, "event_id": event_id}

        except Exception as exc:
            self._log("ERROR", f"Webhook processing failed: {exc}", tenant_id)
            # Publish failure event
            try:
                import asyncio
                from ...shared.event_bus import get_event_bus
                bus = get_event_bus()
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    bus.publish(
                        "webhook.failed",
                        self.plugin_id,
                        tenant_id,
                        {"original_event": event_type, "error": str(exc)},
                    )
                )
                loop.close()
            except Exception:
                pass
            return {"processed": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # IP allowlist check (called externally)
    # ------------------------------------------------------------------

    def check_ip_allowed(self, remote_ip: str, config: Optional[dict] = None) -> bool:
        """Returns True if remote_ip is in the allowed list, or if no list is configured."""
        allowed = self._get_allowed_ips(config)
        if not allowed:
            return True
        return remote_ip in allowed

    # ------------------------------------------------------------------
    # Standard plugin methods
    # ------------------------------------------------------------------

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Return recent webhook delivery logs for this tenant."""
        try:
            from ...backend.db import get_panel_db
            db = get_panel_db()
            rows = db.fetch_all(
                """
                SELECT * FROM connector_logs
                WHERE tenant_id = ? AND connector_id = ?
                ORDER BY timestamp DESC LIMIT 50
                """,
                (tenant_id, self.plugin_id),
            )
            return rows
        except Exception:
            return []

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "message": "Generic Webhook Listener is running",
            "signature_verification": bool(self._get_secret()),
        }

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        return True  # Webhook listener is always "connected"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "verify_signature": {"type": "boolean", "default": True},
                "secret": {"type": "string", "format": "secret", "description": "HMAC signing secret"},
                "event_type_header": {"type": "string", "default": "X-Webhook-Event"},
                "allowed_ips": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "IP allowlist. Leave empty to allow all sources.",
                },
            },
        }

    def get_permissions(self) -> list[str]:
        return ["webhooks.receive", "events.publish"]

    def get_events(self) -> list[str]:
        return ["webhook.received", "webhook.failed", "webhook.retry"]
