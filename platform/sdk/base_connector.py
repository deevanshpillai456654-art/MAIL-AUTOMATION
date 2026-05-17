"""
BaseConnector — the single base class every connector/plugin must extend.

Builds on the existing ConnectorBase (connectors/sdk/base.py) but adds:
  - ConnectorContext injection (event bus, queue, auth, metrics)
  - Workflow node registration
  - UI widget contribution
  - Tenant-aware multi-tenancy from the ground up
  - Permission checking through the runtime engine
  - Graceful shutdown with cleanup hooks
"""
from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class BaseConnector:
    """
    Foundation class for ALL connectors and plugins in the runtime.

    Subclasses MUST provide:
      - PLUGIN_ID: str        — unique identifier (e.g., "salesforce")
      - PLUGIN_NAME: str      — human-readable name
      - PLUGIN_VERSION: str   — semver string
      - CAPABILITIES: List[str]  — capability names this plugin provides

    Subclasses SHOULD override:
      - on_startup()       — async, called when plugin starts
      - on_shutdown()      — async, called when plugin stops
      - health_check()     — async, returns {"healthy": bool, ...}
      - sync(entity, since) — async data synchronization

    Subclasses MAY override:
      - on_event(event)    — receive subscribed runtime events
      - register_workflow_nodes() — return list of WorkflowNode objects
      - register_ui_widgets()     — return list of widget descriptors
    """

    PLUGIN_ID:      str = "base"
    PLUGIN_NAME:    str = "Base Connector"
    PLUGIN_VERSION: str = "1.0.0"
    CAPABILITIES:   List[str] = []
    EVENT_SUBSCRIPTIONS: List[str] = []   # event type patterns to subscribe to

    def __init__(self, context: Optional["ConnectorContext"] = None) -> None:
        self.ctx    = context
        self.log    = logging.getLogger(f"plugin.{self.PLUGIN_ID}")
        self._subs: List[str] = []  # subscription IDs to clean up on shutdown

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def on_startup(self) -> None:
        """Called once when the plugin is started by the lifecycle manager."""
        self.log.info("%s started", self.PLUGIN_NAME)

    async def on_shutdown(self) -> None:
        """Called when the plugin is stopped. Clean up resources here."""
        if self.ctx and self.ctx.event_bus:
            for sid in self._subs:
                self.ctx.event_bus.unsubscribe(sid)
        self.log.info("%s stopped", self.PLUGIN_NAME)

    async def on_install(self) -> None:
        """Called once when the plugin is first installed for a tenant."""

    async def on_uninstall(self) -> None:
        """Called when the plugin is removed for a tenant."""

    # ── Event subscription ────────────────────────────────────────────────

    def subscribe_events(self, patterns: List[str], tenant_id: Optional[str] = None) -> None:
        """Subscribe to runtime events. Subscriptions are cleaned up on shutdown."""
        if not (self.ctx and self.ctx.event_bus):
            return
        sid = self.ctx.event_bus.subscribe(
            patterns,
            self._handle_event,
            sub_id=f"{self.PLUGIN_ID}_evtsub",
            tenant_filter=tenant_id,
        )
        self._subs.append(sid)

    async def _handle_event(self, event: Any) -> None:
        try:
            await self.on_event(event)
        except Exception as exc:
            self.log.error("on_event raised for %s: %s", event.event_type, exc, exc_info=True)

    async def on_event(self, event: Any) -> None:
        """Override to handle subscribed events. Default: no-op."""

    # ── Core interface ────────────────────────────────────────────────────

    async def sync(self, entity: str, *, since: Optional[str] = None) -> Dict[str, Any]:
        """Override to implement data synchronization."""
        return {"synced": 0, "entity": entity}

    async def health_check(self) -> Dict[str, Any]:
        """Override to implement health checking."""
        return {"healthy": True, "plugin_id": self.PLUGIN_ID}

    # ── Publishing ────────────────────────────────────────────────────────

    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        tenant_id: Optional[str] = None,
    ) -> Optional[str]:
        """Publish an event through the runtime event bus."""
        if not (self.ctx and self.ctx.event_bus):
            self.log.warning("publish: no event bus available")
            return None
        tid = tenant_id or (self.ctx.tenant_id if self.ctx else "__system__")
        return await self.ctx.event_bus.publish(
            event_type, self.PLUGIN_ID, tid, payload
        )

    # ── Capability extension points ────────────────────────────────────────

    def register_workflow_nodes(self) -> List[Any]:
        """Return list of WorkflowNode objects this plugin contributes."""
        return []

    def register_ui_widgets(self) -> List[Dict[str, Any]]:
        """Return list of UI widget descriptors this plugin contributes."""
        return []

    def get_registration(self) -> Dict[str, Any]:
        """Return a service registry PluginRegistration-compatible dict."""
        return {
            "plugin_id":            self.PLUGIN_ID,
            "name":                 self.PLUGIN_NAME,
            "version":              self.PLUGIN_VERSION,
            "capabilities":         [{"name": c} for c in self.CAPABILITIES],
            "event_types_consumed": self.EVENT_SUBSCRIPTIONS,
            "provides_workflow_nodes": [n.__class__.__name__ for n in self.register_workflow_nodes()],
            "provides_ui_widgets":  [w.get("widget_id", "") for w in self.register_ui_widgets()],
        }


# ---------------------------------------------------------------------------
# ConnectorContext — dependency injection container for a plugin instance
# ---------------------------------------------------------------------------

class ConnectorContext:
    """
    Runtime context injected into every connector/plugin instance.

    Provides access to all platform services without direct imports.
    """

    def __init__(
        self,
        plugin_id:    str,
        tenant_id:    str,
        config:       Dict[str, Any],
        *,
        event_bus:    Optional[Any] = None,
        queue:        Optional[Any] = None,
        db:           Optional[Any] = None,
        auth:         Optional[Any] = None,
        metrics:      Optional[Any] = None,
        permissions:  Optional[Any] = None,
        sandbox:      Optional[Any] = None,
        service_registry: Optional[Any] = None,
    ) -> None:
        self.plugin_id  = plugin_id
        self.tenant_id  = tenant_id
        self.config     = config

        # Platform services (injected by the runtime at plugin startup)
        self.event_bus  = event_bus
        self.queue      = queue
        self.db         = db
        self.auth       = auth
        self.metrics    = metrics
        self.permissions = permissions
        self.sandbox    = sandbox
        self.service_registry = service_registry

    def require_permission(self, permission: str) -> None:
        if self.permissions:
            self.permissions.require(self.plugin_id, self.tenant_id, permission)

    def has_permission(self, permission: str) -> bool:
        if not self.permissions:
            return True
        return self.permissions.has(self.plugin_id, self.tenant_id, permission)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)
