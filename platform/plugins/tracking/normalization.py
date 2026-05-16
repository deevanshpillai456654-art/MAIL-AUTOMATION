from __future__ import annotations
from typing import Dict
from sdk.models import RawTrackingEvent, NormalizedTrackingEvent

DEFAULT_STATUS_MAP = {
    "ARRIVED_AT_PORT": "ARRIVED_PORT",
    "PORT_ENTRY_COMPLETE": "ARRIVED_PORT",
    "GATE_IN_COMPLETE": "ARRIVED_PORT",
    "GATE_IN": "GATED_IN",
    "VESSEL_DEPARTED": "DEPARTED",
    "DEPARTED": "DEPARTED",
    "CUSTOMS_CLEARANCE_STARTED": "CUSTOMS_STARTED",
    "ASSESSMENT_PENDING": "CUSTOMS_ASSESSMENT_PENDING",
    "EXAMINATION_PENDING": "CUSTOMS_EXAMINATION_PENDING",
    "DUTY_PAYMENT_PENDING": "DUTY_PENDING",
    "OUT_OF_CHARGE": "OUT_OF_CHARGE",
    "DELIVERED": "DELIVERED",
}

class EventNormalizer:
    def __init__(self) -> None:
        self.tenant_maps: Dict[str, Dict[str, str]] = {}

    def set_mapping(self, tenant_id: str, raw_status: str, normalized_status: str) -> None:
        self.tenant_maps.setdefault(tenant_id, {})[raw_status.upper()] = normalized_status.upper()

    def normalize_status(self, tenant_id: str, raw_status: str) -> str:
        raw = (raw_status or "UNKNOWN").upper().replace(" ", "_").replace("-", "_")
        return self.tenant_maps.get(tenant_id, {}).get(raw) or DEFAULT_STATUS_MAP.get(raw) or raw

    def normalize(self, event: RawTrackingEvent) -> NormalizedTrackingEvent:
        normalized = self.normalize_status(event.tenant_id, event.raw_status)
        return NormalizedTrackingEvent(
            tenant_id=event.tenant_id, shipment_key=event.shipment_key, source_system=event.source_system,
            raw_status=event.raw_status, normalized_status=normalized, timestamp=event.timestamp,
            mode=event.mode, metadata=event.metadata
        )
