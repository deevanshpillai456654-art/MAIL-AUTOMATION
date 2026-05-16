from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class WorkflowMode(str, Enum):
    MANUAL = "manual"
    SEMI_AUTOMATIC = "semi_automatic"
    FULL_AUTOMATIC = "full_automatic"


class PluginStatus(str, Enum):
    REGISTERED = "registered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass
class TenantContext:
    tenant_id: str
    branch_id: Optional[str] = None
    user_id: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)

    def has_permission(self, permission: str) -> bool:
        return "admin" in self.roles or permission in self.permissions


@dataclass
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    entrypoint: str
    permissions: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    connector_types: List[str] = field(default_factory=list)
    enabled_by_default: bool = False
    sandbox: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PluginManifest":
        required = ["plugin_id", "name", "version", "entrypoint"]
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValueError(f"Plugin manifest missing: {', '.join(missing)}")
        return cls(
            plugin_id=data["plugin_id"],
            name=data["name"],
            version=data["version"],
            entrypoint=data["entrypoint"],
            permissions=list(data.get("permissions", [])),
            hooks=list(data.get("hooks", [])),
            connector_types=list(data.get("connector_types", [])),
            enabled_by_default=bool(data.get("enabled_by_default", False)),
            sandbox=dict(data.get("sandbox", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ShipmentReference:
    shipment_id: Optional[str] = None
    awb: Optional[str] = None
    bl: Optional[str] = None
    container: Optional[str] = None
    invoice: Optional[str] = None
    customer_id: Optional[str] = None


@dataclass
class TimelineItem:
    item_id: str
    tenant_id: str
    shipment_key: str
    source: str
    event_type: str
    title: str
    description: str = ""
    occurred_at: str = field(default_factory=utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ShipmentWorkspace:
    workspace_id: str
    tenant_id: str
    shipment_key: str
    references: ShipmentReference
    assigned_operator: Optional[str] = None
    status: str = "active"
    timeline: List[TimelineItem] = field(default_factory=list)
    notes: List[Dict[str, Any]] = field(default_factory=list)
    approvals: List[Dict[str, Any]] = field(default_factory=list)
    ai_summary: Optional[str] = None
    updated_at: str = field(default_factory=utc_now)

    def add_timeline(self, item: TimelineItem) -> None:
        if item.tenant_id != self.tenant_id:
            raise ValueError("Tenant mismatch while adding timeline item")
        self.timeline.append(item)
        self.timeline.sort(key=lambda x: x.occurred_at)
        self.updated_at = utc_now()


@dataclass
class RawTrackingEvent:
    tenant_id: str
    shipment_key: str
    source_system: str
    raw_status: str
    timestamp: str
    mode: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedTrackingEvent:
    tenant_id: str
    shipment_key: str
    source_system: str
    raw_status: str
    normalized_status: str
    timestamp: str
    mode: str = "unknown"
    dedupe_key: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dedupe_key:
            raw = f"{self.tenant_id}|{self.shipment_key}|{self.source_system}|{self.normalized_status}|{self.timestamp}"
            self.dedupe_key = raw.lower()


@dataclass
class CommunicationMessage:
    message_id: str
    tenant_id: str
    channel: str
    direction: str
    sender: str
    recipient: str
    body: str
    occurred_at: str = field(default_factory=utc_now)
    shipment_refs: ShipmentReference = field(default_factory=ShipmentReference)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentRecord:
    document_id: str
    tenant_id: str
    filename: str
    document_type: str = "unknown"
    risk_level: RiskLevel = RiskLevel.MEDIUM
    confidence: float = 0.0
    extracted_fields: Dict[str, Any] = field(default_factory=dict)
    linked_shipment: Optional[str] = None
    checksum: Optional[str] = None
    storage_uri: Optional[str] = None
    created_at: str = field(default_factory=utc_now)


@dataclass
class ApprovalRequest:
    approval_id: str
    tenant_id: str
    workflow_type: str
    risk_level: RiskLevel
    requester: str
    payload: Dict[str, Any]
    status: str = "pending"
    mode: WorkflowMode = WorkflowMode.SEMI_AUTOMATIC
    reason: str = ""
    created_at: str = field(default_factory=utc_now)
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None


@dataclass
class QueueJob:
    job_id: str
    tenant_id: str
    job_type: str
    payload: Dict[str, Any]
    status: str = "queued"
    attempts: int = 0
    max_attempts: int = 3
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    last_error: Optional[str] = None


@dataclass
class SearchRecord:
    record_id: str
    tenant_id: str
    entity_type: str
    entity_id: str
    text: str
    tokens: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
