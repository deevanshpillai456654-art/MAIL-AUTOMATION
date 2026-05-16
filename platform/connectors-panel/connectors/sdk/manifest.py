"""
ConnectorManifest — static descriptor for every connector.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class OAuthConfig:
    provider_id: str
    auth_url: str
    token_url: str
    scopes: List[str]
    extra_params: Dict[str, str] = field(default_factory=dict)
    supports_refresh: bool = True
    pkce: bool = False


@dataclass
class WebhookConfig:
    events: List[str]
    signature_header: str = "X-Hub-Signature-256"
    signature_algo: str = "sha256"
    verify_ssl: bool = True


@dataclass
class SyncConfig:
    entities: List[str]
    default_interval_seconds: int = 3600
    supports_incremental: bool = True
    supports_full: bool = True


@dataclass
class HealthCheck:
    name: str
    endpoint: str
    method: str = "GET"
    expected_status: int = 200
    timeout_seconds: int = 10


@dataclass
class Permission:
    scope: str
    label: str
    description: str
    required: bool = True


@dataclass
class ConnectorManifest:
    # Identity
    id: str
    name: str
    category: str
    description: str
    version: str = "1.0.0"
    author: str = "MailPilot"
    icon: str = "🔌"
    docs_url: str = ""

    # Capabilities
    oauth: Optional[OAuthConfig] = None
    supports_api_key: bool = False
    supports_webhook: bool = False
    supports_oauth: bool = False
    webhook: Optional[WebhookConfig] = None
    sync: Optional[SyncConfig] = None
    health_checks: List[HealthCheck] = field(default_factory=list)
    permissions: List[Permission] = field(default_factory=list)

    # Lifecycle
    install_requires: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)

    # Events emitted
    emits_events: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "icon": self.icon,
            "supports_oauth": self.supports_oauth,
            "supports_api_key": self.supports_api_key,
            "supports_webhook": self.supports_webhook,
            "oauth_scopes": self.oauth.scopes if self.oauth else [],
            "webhook_events": self.webhook.events if self.webhook else [],
            "sync_entities": self.sync.entities if self.sync else [],
            "permissions": [{"scope": p.scope, "label": p.label, "required": p.required} for p in self.permissions],
            "emits_events": self.emits_events,
            "config_schema": self.config_schema,
        }
