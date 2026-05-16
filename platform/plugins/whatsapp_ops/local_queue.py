from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List
from sdk.models import utc_now

@dataclass
class WhatsAppSendItem:
    message_id: str
    tenant_id: str
    session_id: str
    recipient: str
    body: str
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "pending_approval"
    attempts: int = 0
    created_at: str = field(default_factory=utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

class LocalWhatsAppQueue:
    def __init__(self) -> None:
        self.items: Dict[str, WhatsAppSendItem] = {}

    def enqueue(self, item: WhatsAppSendItem) -> WhatsAppSendItem:
        self.items[item.message_id] = item
        return item

    def mark_ready(self, message_id: str) -> None:
        self.items[message_id].status = "ready_to_send"

    def mark_sent(self, message_id: str) -> None:
        self.items[message_id].status = "sent"

    def mark_failed(self, message_id: str, reason: str) -> None:
        item = self.items[message_id]
        item.status = "failed"
        item.attempts += 1
        item.metadata["last_error"] = reason

    def pending(self, tenant_id: str) -> List[WhatsAppSendItem]:
        return [item for item in self.items.values() if item.tenant_id == tenant_id and item.status not in {"sent"}]
