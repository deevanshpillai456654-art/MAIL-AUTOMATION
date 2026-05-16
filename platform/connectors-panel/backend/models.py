"""
Pydantic v2 models for the MailPilot Connector & Plugin Panel.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ConnectorStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    INSTALLING = "installing"
    FAILED = "failed"
    DEGRADED = "degraded"


class ConnectorCategory(str, Enum):
    COMMUNICATION = "communication"
    ERP = "erp"
    CRM = "crm"
    TRACKING = "tracking"
    OCR = "ocr"
    SEARCH = "search"
    AI = "ai"
    ECOMMERCE = "ecommerce"
    WEBHOOK = "webhook"
    INTERNAL = "internal"


class PluginPermissionLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"


class LogLevel(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    DEBUG = "DEBUG"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"
    CANCELLED = "cancelled"


class PriceTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

class ConnectorManifest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    category: ConnectorCategory
    description: str
    author: str
    icon_url: Optional[str] = None
    status: ConnectorStatus = ConnectorStatus.INACTIVE
    permissions: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    supports_oauth: bool = False
    supports_webhook: bool = False
    supports_api_key: bool = False
    multiTenant: bool = True
    queue_enabled: bool = False
    health_endpoint: Optional[str] = None


class InstalledConnector(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    connector_id: str
    tenant_id: str
    name: str
    category: ConnectorCategory
    status: ConnectorStatus
    version: str
    installed_at: datetime
    last_sync: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    failure_count: int = 0
    retry_count: int = 0
    api_status: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    health_score: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("config", mode="before")
    @classmethod
    def parse_config(cls, v: Any) -> dict[str, Any]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class OAuthToken(BaseModel):
    """OAuth token model — access_token and refresh_token are never exposed in API responses."""
    model_config = ConfigDict(from_attributes=True)

    token_id: str
    connector_id: str
    tenant_id: str
    provider: str
    # These fields are write-only and must NEVER be included in API responses
    access_token: Optional[str] = Field(default=None, exclude=True)
    refresh_token: Optional[str] = Field(default=None, exclude=True)
    expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    is_valid: bool = True

    @field_validator("scopes", mode="before")
    @classmethod
    def parse_scopes(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return [s.strip() for s in v.split(",") if s.strip()]
        return v or []


class OAuthTokenSafe(BaseModel):
    """Safe view of OAuthToken — never exposes token values."""
    model_config = ConfigDict(from_attributes=True)

    token_id: str
    connector_id: str
    tenant_id: str
    provider: str
    expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)
    created_at: datetime
    is_valid: bool = True


class WebhookEndpoint(BaseModel):
    """Webhook endpoint — secret is never exposed in API responses."""
    model_config = ConfigDict(from_attributes=True)

    webhook_id: str
    connector_id: str
    tenant_id: str
    url: str
    secret: Optional[str] = Field(default=None, exclude=True)
    events: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime
    last_triggered: Optional[datetime] = None
    failure_count: int = 0
    success_count: int = 0

    @field_validator("events", mode="before")
    @classmethod
    def parse_events(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return [e.strip() for e in v.split(",") if e.strip()]
        return v or []


class WebhookEndpointSafe(BaseModel):
    """Safe view of WebhookEndpoint — never exposes secret."""
    model_config = ConfigDict(from_attributes=True)

    webhook_id: str
    connector_id: str
    tenant_id: str
    url: str
    events: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime
    last_triggered: Optional[datetime] = None
    failure_count: int = 0
    success_count: int = 0


class QueueStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    queued: int = 0
    processing: int = 0
    dead_letters: int = 0
    total_processed: int = 0
    last_processed_at: Optional[datetime] = None


class ConnectorLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    log_id: str
    connector_id: str
    tenant_id: str
    level: LogLevel
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    @field_validator("metadata", mode="before")
    @classmethod
    def parse_metadata(cls, v: Any) -> dict[str, Any]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class ConnectorHealth(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    connector_id: str
    tenant_id: str
    status: ConnectorStatus
    last_heartbeat: Optional[datetime] = None
    last_sync: Optional[datetime] = None
    failure_count: int = 0
    retry_count: int = 0
    response_latency_ms: Optional[float] = None
    api_quota_used: Optional[int] = None
    api_quota_limit: Optional[int] = None
    token_expires_at: Optional[datetime] = None
    checks: dict[str, Any] = Field(default_factory=dict)

    @field_validator("checks", mode="before")
    @classmethod
    def parse_checks(cls, v: Any) -> dict[str, Any]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class MarketplaceConnector(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    version: str
    category: ConnectorCategory
    description: str
    author: str
    icon_url: Optional[str] = None
    status: ConnectorStatus = ConnectorStatus.INACTIVE
    permissions: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    supports_oauth: bool = False
    supports_webhook: bool = False
    supports_api_key: bool = False
    multiTenant: bool = True
    queue_enabled: bool = False
    health_endpoint: Optional[str] = None
    # Marketplace-specific fields
    install_count: int = 0
    rating: float = Field(default=0.0, ge=0.0, le=5.0)
    is_installed: bool = False
    is_beta: bool = False
    price_tier: PriceTier = PriceTier.FREE


# ---------------------------------------------------------------------------
# Request / Input Models
# ---------------------------------------------------------------------------

class ConnectorInstallRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    connector_id: str
    tenant_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    oauth_code: Optional[str] = None
    api_key: Optional[str] = None

    @field_validator("connector_id", "tenant_id")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field must not be empty")
        return v


class ConnectorConfigUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    config: dict[str, Any] = Field(default_factory=dict)
    is_active: Optional[bool] = None


class WebhookCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    connector_id: str
    tenant_id: str
    url: str
    events: list[str] = Field(default_factory=list)
    secret: Optional[str] = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v

    @field_validator("events")
    @classmethod
    def events_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("At least one event must be specified")
        return v


class EventRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_type: str
    source_connector_id: str
    tenant_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    published_at: datetime
    processed_by: list[str] = Field(default_factory=list)

    @field_validator("payload", mode="before")
    @classmethod
    def parse_payload(cls, v: Any) -> dict[str, Any]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}

    @field_validator("processed_by", mode="before")
    @classmethod
    def parse_processed_by(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return []
        return v or []


class PluginPermission(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plugin_id: str
    tenant_id: str
    permission: PluginPermissionLevel
    granted_at: datetime
    granted_by: str


class QueueJob(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    connector_id: str
    tenant_id: str
    job_type: str
    status: JobStatus = JobStatus.QUEUED
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    max_attempts: int = 3
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("payload", mode="before")
    @classmethod
    def parse_payload(cls, v: Any) -> dict[str, Any]:
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}


class QueueJobCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    connector_id: str
    tenant_id: str
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)


class PluginInfo(BaseModel):
    """Plugin info as read from plugin.json manifest files."""
    model_config = ConfigDict(from_attributes=True)

    plugin_id: str
    name: str
    version: str
    plugin_type: str = "plugin"
    category: str
    description: str
    author: str
    enabled: bool = False
    multiTenant: bool = True
    supports_oauth: bool = False
    supports_api_key: bool = False
    supports_webhook: bool = False
    queue_enabled: bool = False
    permissions: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    path: Optional[str] = None


class PermissionGrantRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tenant_id: str
    permission: PluginPermissionLevel
    granted_by: str


class OAuthTokenCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    connector_id: str
    tenant_id: str
    provider: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)


class EventPublishRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_type: str
    source_connector_id: str
    tenant_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Response wrappers
# ---------------------------------------------------------------------------

class APIResponse(BaseModel):
    success: bool = True
    message: str = "OK"
    data: Any = None


class PaginatedResponse(BaseModel):
    items: list[Any]
    total: int
    page: int = 1
    page_size: int = 50
    has_more: bool = False
