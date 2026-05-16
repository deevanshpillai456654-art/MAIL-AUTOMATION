"""
Webhook system for AI Email Organizer
"""

import json
import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum
from backend.security.ssrf import validate_outbound_url
from backend.security.audit import record_security_event

_log = logging.getLogger(__name__)


class WebhookEvent(str, Enum):
    EMAIL_CLASSIFIED = "email.classified"
    RULE_TRIGGERED = "rule.triggered"
    HIGH_PRIORITY = "email.high_priority"
    SYNC_COMPLETE = "sync.complete"
    USER_CORRECTION = "user.correction"


class Webhook:
    def __init__(
        self,
        url: str,
        events: List[WebhookEvent],
        name: str = "",
        enabled: bool = True,
        secret: str = ""
    ):
        self.url = url
        self.events = events
        self.name = name or url[:50]
        self.enabled = enabled
        self.secret = secret
        self.id = f"wh_{datetime.now().timestamp()}"
        self.created_at = datetime.now()
        self.last_triggered = None
        self.success_count = 0
        self.failure_count = 0

    def should_trigger(self, event: WebhookEvent) -> bool:
        return self.enabled and event in self.events

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "events": [e.value for e in self.events],
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "last_triggered": self.last_triggered.isoformat() if self.last_triggered else None,
            "success_count": self.success_count,
            "failure_count": self.failure_count
        }


class WebhookManager:
    def __init__(self, storage_path: str = None):
        self.webhooks: List[Webhook] = []
        self._load_webhooks(storage_path)

    def _load_webhooks(self, storage_path: str):
        if storage_path and __import__('os').path.exists(storage_path):
            try:
                with open(storage_path, 'r') as f:
                    data = json.load(f)
                    for wh_data in data.get('webhooks', []):
                        wh = Webhook(
                            url=wh_data['url'],
                            events=[WebhookEvent(e) for e in wh_data['events']],
                            name=wh_data.get('name', ''),
                            enabled=wh_data.get('enabled', True),
                            secret=wh_data.get('secret', '')
                        )
                        wh.id = wh_data.get('id', wh.id)
                        self.webhooks.append(wh)
            except Exception as exc:
                _log.warning("Failed to load webhooks from %s: %s", storage_path, exc)

    def _save_webhooks(self, storage_path: str):
        if storage_path:
            with open(storage_path, 'w') as f:
                json.dump({
                    'webhooks': [wh.to_dict() for wh in self.webhooks]
                }, f, indent=2)

    def add_webhook(self, webhook: Webhook, storage_path: str = None):
        decision = validate_outbound_url(webhook.url)
        if not decision.allowed:
            record_security_event("webhook_registration_blocked", severity="warning", details={"webhook_id": webhook.id, "reason": decision.reason})
            raise ValueError(f"Webhook URL blocked: {decision.reason}")
        self.webhooks.append(webhook)
        self._save_webhooks(storage_path)

    def remove_webhook(self, webhook_id: str, storage_path: str = None):
        self.webhooks = [wh for wh in self.webhooks if wh.id != webhook_id]
        self._save_webhooks(storage_path)

    def get_webhooks(self) -> List[Dict]:
        return [wh.to_dict() for wh in self.webhooks]

    def trigger(self, event: WebhookEvent, payload: Dict, storage_path: str = None):
        triggered = []

        for webhook in self.webhooks:
            if webhook.should_trigger(event):
                success = self._send_webhook(webhook, event, payload)
                if success:
                    triggered.append(webhook.id)

        return triggered

    def _send_webhook(self, webhook: Webhook, event: WebhookEvent, payload: Dict) -> bool:
        import hmac
        import hashlib

        decision = validate_outbound_url(webhook.url)
        if not decision.allowed:
            webhook.failure_count += 1
            record_security_event("webhook_delivery_blocked", severity="warning", details={"webhook_id": webhook.id, "reason": decision.reason})
            return False

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event.value,
            "X-Webhook-ID": webhook.id
        }

        if webhook.secret:
            signature = hmac.new(
                webhook.secret.encode(),
                json.dumps(payload).encode(),
                hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = signature

        try:
            response = requests.post(
                webhook.url,
                json=payload,
                headers=headers,
                timeout=10
            )

            webhook.last_triggered = datetime.now()

            if response.ok:
                webhook.success_count += 1
                return True
            else:
                webhook.failure_count += 1
                return False

        except Exception as e:
            webhook.failure_count += 1
            return False
        finally:
            self._save_webhooks(None)


def notify_webhook(event: WebhookEvent, data: Dict):
    """Send webhook notification"""
    payload = {
        "event": event.value,
        "timestamp": datetime.now().isoformat(),
        "data": data
    }

    import os
    storage_path = os.path.join(os.path.dirname(__file__), "..", "data", "webhooks.json")
    storage_path = os.path.normpath(storage_path)

    os.makedirs(os.path.dirname(storage_path), exist_ok=True)

    manager = WebhookManager(storage_path)
    return manager.trigger(event, payload, storage_path)