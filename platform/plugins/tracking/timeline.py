from __future__ import annotations
from typing import Dict, List
from sdk.models import NormalizedTrackingEvent

class ShipmentTimelineStore:
    def __init__(self) -> None:
        self.events: Dict[str, Dict[str, NormalizedTrackingEvent]] = {}

    def _key(self, tenant_id: str, shipment_key: str) -> str:
        return f"{tenant_id}:{shipment_key}"

    def add(self, event: NormalizedTrackingEvent) -> bool:
        key = self._key(event.tenant_id, event.shipment_key)
        bucket = self.events.setdefault(key, {})
        if event.dedupe_key in bucket:
            return False
        bucket[event.dedupe_key] = event
        return True

    def timeline(self, tenant_id: str, shipment_key: str) -> List[NormalizedTrackingEvent]:
        values = list(self.events.get(self._key(tenant_id, shipment_key), {}).values())
        return sorted(values, key=lambda e: e.timestamp)
