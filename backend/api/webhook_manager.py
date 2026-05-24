"""
Webhook Manager
=================

Webhook management:
- Webhook registration
- Event filtering
- Retry logic
- Signature verification
- Payload transformation
"""

import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import requests

from backend.security.audit import record_security_event
from backend.security.redaction import redact_text
from backend.security.ssrf import validate_outbound_url

logger = logging.getLogger("webhook.manager")


class WebhookEvent(Enum):
    EMAIL_RECEIVED = "email.received"
    EMAIL_CLASSIFIED = "email.classified"
    EMAIL_MOVED = "email.moved"
    RULE_TRIGGERED = "rule.triggered"
    SYNC_COMPLETE = "sync.complete"
    ACCOUNT_CONNECTED = "account.connected"


class WebhookStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    FAILED = "failed"


@dataclass
class Webhook:
    """Webhook configuration"""
    webhook_id: str
    url: str
    events: List[WebhookEvent]
    status: WebhookStatus = WebhookStatus.ACTIVE
    secret: Optional[str] = None
    retry_count: int = 3
    retry_delay: float = 5.0
    created_at: float = field(default_factory=time.time)
    last_triggered: Optional[float] = None
    failure_count: int = 0


class WebhookManager:
    """
    Webhook manager.
    """

    def __init__(self):
        self._webhooks: Dict[str, Webhook] = {}
        self._lock = threading.RLock()

        logger.info("WebhookManager initialized")

    def register(
        self,
        webhook_id: str,
        url: str,
        events: List[str],
        secret: str = None
    ) -> Webhook:
        """Register webhook"""
        decision = validate_outbound_url(url)
        if not decision.allowed:
            record_security_event("webhook_registration_blocked", severity="warning", details={"webhook_id": webhook_id, "reason": decision.reason})
            raise ValueError(f"Webhook URL blocked: {decision.reason}")
        with self._lock:
            webhook_events = [WebhookEvent(e) for e in events]

            webhook = Webhook(
                webhook_id=webhook_id,
                url=url,
                events=webhook_events,
                secret=secret
            )

            self._webhooks[webhook_id] = webhook
            logger.info(f"Webhook registered: {webhook_id}")

            return webhook

    def unregister(self, webhook_id: str) -> bool:
        """Unregister webhook"""
        with self._lock:
            if webhook_id in self._webhooks:
                del self._webhooks[webhook_id]
                return True
            return False

    def trigger(self, event: WebhookEvent, data: Dict[str, Any]) -> int:
        """Trigger webhooks for event"""
        triggered = 0

        with self._lock:
            webhooks = [
                w for w in self._webhooks.values()
                if w.status == WebhookStatus.ACTIVE and event in w.events
            ]

        for webhook in webhooks:
            if self._send_webhook(webhook, event, data):
                triggered += 1
                webhook.last_triggered = time.time()
                webhook.failure_count = 0
            else:
                webhook.failure_count += 1
                if webhook.failure_count >= webhook.retry_count:
                    webhook.status = WebhookStatus.FAILED

        return triggered

    def _send_webhook(self, webhook: Webhook, event: WebhookEvent, data: Dict) -> bool:
        """Send webhook request"""
        try:
            decision = validate_outbound_url(webhook.url)
            if not decision.allowed:
                record_security_event("webhook_delivery_blocked", severity="warning", details={"webhook_id": webhook.webhook_id, "reason": decision.reason})
                return False
            payload = json.dumps({
                "event": event.value,
                "timestamp": time.time(),
                "data": data
            })

            headers = {"Content-Type": "application/json"}

            # Add signature if secret
            if webhook.secret:
                signature = hmac.new(
                    webhook.secret.encode(),
                    payload.encode(),
                    hashlib.sha256
                ).hexdigest()
                headers["X-Webhook-Signature"] = signature

            response = requests.post(
                webhook.url,
                data=payload,
                headers=headers,
                timeout=10
            )

            return response.status_code == 200

        except Exception as e:
            logger.error("Webhook send error for %s: %s", webhook.webhook_id, redact_text(str(e), max_length=160))
            return False

    def get_webhook(self, webhook_id: str) -> Optional[Webhook]:
        """Get webhook"""
        return self._webhooks.get(webhook_id)

    def get_stats(self) -> Dict:
        """Get webhook stats"""
        return {
            "total": len(self._webhooks),
            "active": sum(1 for w in self._webhooks.values() if w.status == WebhookStatus.ACTIVE),
            "failed": sum(1 for w in self._webhooks.values() if w.status == WebhookStatus.FAILED)
        }


# Global webhook manager
_webhook_manager: Optional[WebhookManager] = None


def get_webhook_manager() -> WebhookManager:
    """Get global webhook manager"""
    global _webhook_manager
    if _webhook_manager is None:
        _webhook_manager = WebhookManager()
    return _webhook_manager


__all__ = ["WebhookManager", "Webhook", "WebhookEvent", "WebhookStatus", "get_webhook_manager"]
