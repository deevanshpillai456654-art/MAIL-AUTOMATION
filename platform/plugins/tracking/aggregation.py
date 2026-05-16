from __future__ import annotations
from typing import Iterable, List
from sdk.models import RawTrackingEvent, NormalizedTrackingEvent
from plugins.tracking.normalization import EventNormalizer
from plugins.tracking.timeline import ShipmentTimelineStore

class TrackingAggregationEngine:
    def __init__(self) -> None:
        self.normalizer = EventNormalizer()
        self.store = ShipmentTimelineStore()

    def ingest(self, events: Iterable[RawTrackingEvent]) -> dict:
        added = 0
        normalized_items: List[NormalizedTrackingEvent] = []
        for raw in events:
            normalized = self.normalizer.normalize(raw)
            normalized_items.append(normalized)
            if self.store.add(normalized):
                added += 1
        return {"received": len(normalized_items), "added": added, "duplicates": len(normalized_items) - added}

    def timeline(self, tenant_id: str, shipment_key: str) -> list[dict]:
        return [event.__dict__ for event in self.store.timeline(tenant_id, shipment_key)]
