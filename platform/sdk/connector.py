from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Protocol
from sdk.models import RawTrackingEvent, TenantContext, utc_now

@dataclass
class ConnectorResult:
    connector_id: str
    tenant_id: str
    success: bool
    records: List[Dict[str, Any]] = field(default_factory=list)
    events: List[RawTrackingEvent] = field(default_factory=list)
    error: str | None = None
    created_at: str = field(default_factory=utc_now)

class ConnectorProtocol(Protocol):
    connector_id: str
    connector_type: str
    def health(self, context: TenantContext) -> Dict[str, Any]: ...
    def fetch(self, context: TenantContext, **kwargs: Any) -> ConnectorResult: ...

class BaseConnector:
    connector_id = "base"
    connector_type = "base"

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.timeout_seconds = int(self.config.get("timeout_seconds", 30))
        self.rate_limit_key = self.config.get("rate_limit_key", self.connector_id)

    def health(self, context: TenantContext) -> Dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "connector_type": self.connector_type,
            "tenant_id": context.tenant_id,
            "status": "ready",
            "checked_at": utc_now(),
        }

    def validate_context(self, context: TenantContext) -> None:
        if not context.tenant_id:
            raise ValueError("tenant_id is required for connector execution")

    def fetch(self, context: TenantContext, **kwargs: Any) -> ConnectorResult:
        self.validate_context(context)
        return ConnectorResult(connector_id=self.connector_id, tenant_id=context.tenant_id, success=True)

    def transform(self, context: TenantContext, records: Iterable[Dict[str, Any]]) -> List[RawTrackingEvent]:
        self.validate_context(context)
        events: List[RawTrackingEvent] = []
        for record in records:
            shipment_key = str(record.get("shipment_key") or record.get("shipment") or record.get("awb") or record.get("container") or "UNKNOWN")
            events.append(RawTrackingEvent(
                tenant_id=context.tenant_id,
                shipment_key=shipment_key,
                source_system=self.connector_id,
                raw_status=str(record.get("status") or record.get("raw_status") or "UNKNOWN"),
                timestamp=str(record.get("timestamp") or utc_now()),
                mode=str(record.get("mode") or "unknown"),
                metadata=dict(record),
            ))
        return events

class RESTConnector(BaseConnector):
    connector_type = "rest_api"
    def fetch(self, context: TenantContext, **kwargs: Any) -> ConnectorResult:
        self.validate_context(context)
        # Adapter shell: real network call should be implemented per provider.
        records = list(kwargs.get("records", []))
        return ConnectorResult(self.connector_id, context.tenant_id, True, records=records, events=self.transform(context, records))

class WebhookConnector(BaseConnector):
    connector_type = "webhook"
    def receive(self, context: TenantContext, payload: Dict[str, Any]) -> ConnectorResult:
        self.validate_context(context)
        records = payload.get("events") if isinstance(payload.get("events"), list) else [payload]
        return ConnectorResult(self.connector_id, context.tenant_id, True, records=records, events=self.transform(context, records))

class CSVConnector(BaseConnector):
    connector_type = "csv"
    def parse_rows(self, context: TenantContext, rows: Iterable[Dict[str, Any]]) -> ConnectorResult:
        self.validate_context(context)
        records = list(rows)
        return ConnectorResult(self.connector_id, context.tenant_id, True, records=records, events=self.transform(context, records))

class EmailConnector(BaseConnector):
    connector_type = "email"
    def parse_message(self, context: TenantContext, subject: str, body: str) -> ConnectorResult:
        self.validate_context(context)
        record = {"shipment_key": subject, "status": "EMAIL_RECEIVED", "body": body, "timestamp": utc_now()}
        return ConnectorResult(self.connector_id, context.tenant_id, True, records=[record], events=self.transform(context, [record]))
