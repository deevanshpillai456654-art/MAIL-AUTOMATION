from __future__ import annotations
from typing import Dict, List
from sdk.models import CommunicationMessage

class UnifiedCommunicationTimeline:
    def __init__(self) -> None:
        self.messages: Dict[str, CommunicationMessage] = {}

    def add(self, message: CommunicationMessage) -> None:
        self.messages[message.message_id] = message

    def for_shipment(self, tenant_id: str, shipment_key: str) -> List[CommunicationMessage]:
        return sorted([
            m for m in self.messages.values()
            if m.tenant_id == tenant_id and shipment_key in {m.shipment_refs.shipment_id, m.shipment_refs.awb, m.shipment_refs.bl, m.shipment_refs.container, m.shipment_refs.invoice}
        ], key=lambda m: m.occurred_at)
