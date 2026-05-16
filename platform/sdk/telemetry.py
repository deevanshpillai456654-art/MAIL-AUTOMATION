from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

@dataclass
class TelemetryEvent:
    event_type: str
    tenant_id: str
    severity: str = "info"
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class TelemetrySink:
    def __init__(self) -> None:
        self.events: List[TelemetryEvent] = []

    def emit(self, event_type: str, tenant_id: str, message: str = "", severity: str = "info", **metadata: Any) -> TelemetryEvent:
        event = TelemetryEvent(event_type=event_type, tenant_id=tenant_id, message=message, severity=severity, metadata=metadata)
        self.events.append(event)
        return event

    def latest(self, limit: int = 50) -> List[TelemetryEvent]:
        return self.events[-limit:]
