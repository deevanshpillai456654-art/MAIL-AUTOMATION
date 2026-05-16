"""
MailPilot Plugin SDK

Provides base classes for building connector plugins:
- BasePlugin          — abstract base for all plugins
- ConnectorPlugin     — for data sync connectors
- OAuthPlugin         — for OAuth 2.0 connectors
- WebhookPlugin       — for inbound webhook connectors
"""
from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConnectorSyncResult:
    """Result returned by ConnectorPlugin.sync()."""
    success: bool
    records_processed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "records_processed": self.records_processed,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# BasePlugin
# ---------------------------------------------------------------------------

class BasePlugin(abc.ABC):
    """
    Abstract base class for all MailPilot plugins.

    Subclasses must implement the abstract properties and methods.
    All lifecycle methods return True/False to indicate success.
    """

    # ------------------------------------------------------------------
    # Abstract identity properties
    # ------------------------------------------------------------------

    @property
    @abc.abstractmethod
    def plugin_id(self) -> str:
        """Unique plugin identifier (matches manifest 'name' field)."""
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable plugin name."""
        ...

    @property
    @abc.abstractmethod
    def version(self) -> str:
        """Plugin version string (semver)."""
        ...

    @property
    @abc.abstractmethod
    def category(self) -> str:
        """Plugin category (matches ConnectorCategory enum values)."""
        ...

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    def on_install(self, tenant_id: str, config: dict[str, Any]) -> bool:
        """
        Called when the plugin is installed for a tenant.
        Override to perform one-time setup (DB migrations, API registration, etc.).
        Returns True on success.
        """
        return True

    def on_uninstall(self, tenant_id: str) -> bool:
        """
        Called when the plugin is uninstalled for a tenant.
        Override to clean up resources.
        Returns True on success.
        """
        return True

    def on_enable(self, tenant_id: str) -> bool:
        """Called when the plugin is enabled for a tenant."""
        return True

    def on_disable(self, tenant_id: str) -> bool:
        """Called when the plugin is disabled for a tenant."""
        return True

    # ------------------------------------------------------------------
    # Health and data
    # ------------------------------------------------------------------

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        """
        Returns a health check dict with at minimum:
          {"status": "ok"|"degraded"|"error", "message": str}
        """
        return {"status": "ok", "message": "Plugin is running"}

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """
        Fetch data from the external service.
        Returns a list of record dicts.
        """
        return []

    def handle_event(self, event_type: str, payload: dict[str, Any], tenant_id: str) -> None:
        """
        Handle an incoming platform event.
        Override to react to events published by other connectors.
        """
        pass

    # ------------------------------------------------------------------
    # Capabilities
    # ------------------------------------------------------------------

    def get_permissions(self) -> list[str]:
        """Return the list of permission strings this plugin requires."""
        return []

    def get_events(self) -> list[str]:
        """Return the list of event types this plugin publishes."""
        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _log(self, level: str, message: str, tenant_id: str = "system", metadata: Optional[dict] = None) -> None:
        """Write a log entry via the panel logging system."""
        try:
            from ..backend.logs import write_log
            write_log(self.plugin_id, tenant_id, level, message, metadata)
        except Exception:
            import logging
            logging.getLogger(self.plugin_id).log(
                {"INFO": 20, "WARN": 30, "ERROR": 40, "DEBUG": 10}.get(level.upper(), 20),
                message,
            )


# ---------------------------------------------------------------------------
# ConnectorPlugin
# ---------------------------------------------------------------------------

class ConnectorPlugin(BasePlugin, abc.ABC):
    """
    Base class for connector-type plugins that sync data with external APIs.
    """

    def sync(self, tenant_id: str) -> ConnectorSyncResult:
        """
        Perform a full data sync for the given tenant.
        Override this method to implement the sync logic.
        Returns a ConnectorSyncResult.
        """
        start = time.monotonic()
        result = ConnectorSyncResult(success=False)
        try:
            records = self.fetch_data(tenant_id)
            result.records_processed = len(records)
            result.success = True
        except Exception as exc:
            result.add_error(str(exc))
            result.success = False
        finally:
            result.duration_ms = (time.monotonic() - start) * 1000
        return result

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        """
        Test whether the connector can reach the external API.
        Override to perform an actual connectivity check.
        Returns True if the connection is valid.
        """
        return False

    def get_config_schema(self) -> dict[str, Any]:
        """
        Return a JSON Schema dict describing the plugin's required configuration.
        Example::

            {
                "type": "object",
                "required": ["api_key"],
                "properties": {
                    "api_key": {"type": "string", "description": "API Key"}
                }
            }
        """
        return {"type": "object", "properties": {}}


# ---------------------------------------------------------------------------
# OAuthPlugin
# ---------------------------------------------------------------------------

class OAuthPlugin(ConnectorPlugin, abc.ABC):
    """
    Base class for OAuth 2.0 connector plugins.
    Extends ConnectorPlugin with OAuth authorization code flow methods.
    """

    @abc.abstractmethod
    def get_auth_url(self, tenant_id: str, redirect_uri: str) -> str:
        """
        Build and return the OAuth authorization URL for the tenant.
        The URL should include all required query parameters (client_id, scope, etc.)
        """
        ...

    @abc.abstractmethod
    def exchange_code(self, tenant_id: str, code: str) -> dict[str, Any]:
        """
        Exchange an authorization code for access/refresh tokens.
        Returns a dict with at minimum: {"access_token": str, "expires_in": int, "token_type": str}
        Optionally: {"refresh_token": str, "scope": str}
        """
        ...

    def refresh_token(self, tenant_id: str) -> dict[str, Any]:
        """
        Use the stored refresh token to get a new access token.
        Returns the same structure as exchange_code.
        Raises NotImplementedError if the provider does not support refresh.
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not implement token refresh")

    def get_stored_token(self, tenant_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve and decrypt the stored access token for this tenant.
        Returns None if no valid token exists.
        """
        try:
            from ..backend.db import get_panel_db
            from ..shared.utils import decrypt_secret
            db = get_panel_db()
            row = db.fetch_one(
                "SELECT * FROM oauth_tokens WHERE connector_id = ? AND tenant_id = ? AND is_valid = 1 ORDER BY created_at DESC LIMIT 1",
                (self.plugin_id, tenant_id),
            )
            if not row:
                return None
            import json
            return {
                "access_token": decrypt_secret(row["access_token_enc"]),
                "refresh_token": decrypt_secret(row["refresh_token_enc"]) if row.get("refresh_token_enc") else None,
                "expires_at": row.get("expires_at"),
                "scopes": json.loads(row.get("scopes", "[]")),
            }
        except Exception:
            return None


# ---------------------------------------------------------------------------
# WebhookPlugin
# ---------------------------------------------------------------------------

class WebhookPlugin(ConnectorPlugin, abc.ABC):
    """
    Base class for webhook-driven connector plugins.
    Extends ConnectorPlugin with inbound webhook handling.
    """

    @abc.abstractmethod
    def handle_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        tenant_id: str,
    ) -> dict[str, Any]:
        """
        Process an inbound webhook payload.

        Args:
            payload:   Parsed JSON body from the webhook request.
            headers:   HTTP headers from the webhook request.
            tenant_id: The tenant this webhook is associated with.

        Returns:
            A dict describing what was processed, e.g.:
            {"processed": True, "events_published": 3, "message_ids": [...]}
        """
        ...

    @abc.abstractmethod
    def validate_signature(
        self,
        payload: bytes,
        headers: dict[str, str],
    ) -> bool:
        """
        Validate the webhook signature/authenticity.

        Args:
            payload:  Raw request body bytes (before JSON parsing).
            headers:  HTTP request headers.

        Returns:
            True if the signature is valid, False otherwise.
        """
        ...

    def get_verify_token(self) -> Optional[str]:
        """
        Return the verify token for webhook subscription verification
        (used by providers like Facebook/WhatsApp).
        Override if your webhook provider uses a hub.verify_token challenge.
        """
        import os
        return os.environ.get(f"{self.plugin_id.upper()}_WEBHOOK_VERIFY_TOKEN")
