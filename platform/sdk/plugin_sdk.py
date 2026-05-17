"""
PluginSDK — unified facade that bundles all per-plugin SDK components.

Usage::

    from platform.sdk.plugin_sdk import PluginSDK

    class MyConnector(BaseConnector):
        async def on_startup(self):
            sdk = PluginSDK(self.ctx)
            sdk.events.on("crm.*", self.handle_crm_event)
            sdk.auth.store_api_key(self.ctx.config["api_key"])
            sdk.metrics.increment("startup.count")
"""
from __future__ import annotations

from typing import Any, Optional

from .auth_sdk     import AuthSDK
from .event_sdk    import EventSDK
from .metrics_sdk  import MetricsSDK
from .queue_sdk    import QueueSDK
from .workflow_sdk import WorkflowSDK


class PluginSDK:
    """
    Single-object access point for all SDK subsystems.

    Pass the ConnectorContext received at plugin startup and this class
    provides lazy-initialized sub-SDKs:

        sdk = PluginSDK(self.ctx)
        sdk.events    → EventSDK
        sdk.queue     → QueueSDK
        sdk.auth      → AuthSDK
        sdk.metrics   → MetricsSDK
        sdk.workflow  → WorkflowSDK
    """

    def __init__(self, context: Any) -> None:
        self._ctx = context
        self._events:   Optional[EventSDK]    = None
        self._queue:    Optional[QueueSDK]    = None
        self._auth:     Optional[AuthSDK]     = None
        self._metrics:  Optional[MetricsSDK]  = None
        self._workflow: Optional[WorkflowSDK] = None

    # ── Lazy accessors ────────────────────────────────────────────────────

    @property
    def events(self) -> EventSDK:
        if self._events is None:
            self._events = EventSDK(self._ctx)
        return self._events

    @property
    def queue(self) -> QueueSDK:
        if self._queue is None:
            self._queue = QueueSDK(self._ctx)
        return self._queue

    @property
    def auth(self) -> AuthSDK:
        if self._auth is None:
            self._auth = AuthSDK(self._ctx)
        return self._auth

    @property
    def metrics(self) -> MetricsSDK:
        if self._metrics is None:
            self._metrics = MetricsSDK(self._ctx)
        return self._metrics

    @property
    def workflow(self) -> WorkflowSDK:
        if self._workflow is None:
            self._workflow = WorkflowSDK(self._ctx)
        return self._workflow

    # ── Context pass-through ──────────────────────────────────────────────

    @property
    def plugin_id(self) -> str:
        return getattr(self._ctx, "plugin_id", "unknown")

    @property
    def tenant_id(self) -> str:
        return getattr(self._ctx, "tenant_id", "__system__")

    def get_config(self, key: str, default: Any = None) -> Any:
        cfg = getattr(self._ctx, "config", {})
        return cfg.get(key, default)

    def require_permission(self, permission: str) -> None:
        if hasattr(self._ctx, "require_permission"):
            self._ctx.require_permission(permission)

    def has_permission(self, permission: str) -> bool:
        if hasattr(self._ctx, "has_permission"):
            return self._ctx.has_permission(permission)
        return True

    # ── Cleanup ───────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Unsubscribe all event subscriptions created through this SDK."""
        if self._events:
            self._events.cleanup()
