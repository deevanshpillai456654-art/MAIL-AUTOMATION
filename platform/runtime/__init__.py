"""
Platform Runtime Bootstrap — wires all subsystems into a single PlatformRuntime.

Usage (in the core app startup, e.g. lifespan event)::

    from platform.runtime import PlatformRuntime

    runtime = PlatformRuntime.configure(
        db=get_panel_db(),
        plugins_dir="platform/plugins",
    )
    await runtime.start()

    # In shutdown:
    await runtime.stop()
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class PlatformRuntime:
    """
    Top-level orchestrator for the entire plugin runtime.

    Holds references to every subsystem singleton and provides
    start() / stop() lifecycle methods.
    """

    _instance: Optional["PlatformRuntime"] = None

    @classmethod
    def get(cls) -> Optional["PlatformRuntime"]:
        return cls._instance

    @classmethod
    def configure(
        cls,
        db:           Any,
        *,
        plugins_dir:  str  = "platform/plugins",
        db_path:      str  = "platform/connectors_panel.db",
        hot_reload:   bool = False,
        requests_per_min: int = 600,
    ) -> "PlatformRuntime":
        inst = cls(
            db=db,
            plugins_dir=plugins_dir,
            db_path=db_path,
            hot_reload=hot_reload,
            requests_per_min=requests_per_min,
        )
        cls._instance = inst
        return inst

    def __init__(
        self,
        db:           Any,
        *,
        plugins_dir:  str,
        db_path:      str,
        hot_reload:   bool,
        requests_per_min: int,
    ) -> None:
        self._db           = db
        self._plugins_dir  = plugins_dir
        self._db_path      = db_path
        self._hot_reload   = hot_reload
        self._rpm          = requests_per_min
        self._started      = False

        # ── Subsystems (initialised lazily in start()) ────────────────────
        self.event_bus     = None
        self.event_store   = None
        self.registry      = None
        self.permission_engine = None
        self.sandbox_manager   = None
        self.lifecycle_manager = None
        self.health_monitor    = None
        self.auto_recovery     = None
        self.worker_pool       = None
        self.workflow_engine   = None
        self.ui_registry       = None
        self.node_registry     = None
        self.trigger_registry  = None
        self.schema_registry   = None
        self.metrics           = None
        self.error_tracker     = None
        self.health_dashboard  = None
        self.event_tracer      = None

    # ── Startup ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        log.info("PlatformRuntime: starting …")

        # 1. Observability singletons (needed by everything else)
        from ..observability.metrics        import PluginMetrics
        from ..observability.health_dashboard import HealthDashboard
        from ..observability.error_tracking  import ErrorTracker
        from ..observability.event_tracing   import EventTracer
        self.metrics          = PluginMetrics.get()
        self.health_dashboard = HealthDashboard.get()
        self.error_tracker    = ErrorTracker.get()
        self.event_tracer     = EventTracer.get()

        # 2. Permission engine + sandbox
        from .permissions.permission_engine import PermissionEngine
        from .sandbox.sandbox_manager       import SandboxManager
        self.permission_engine = PermissionEngine()
        self.sandbox_manager   = SandboxManager()

        # 3. Event bus + store
        from .events.event_bus   import RuntimeEventBus
        from .events.event_store import EventStore
        self.event_bus   = RuntimeEventBus.get()
        self.event_store = EventStore(self._db_path)
        self.event_bus.subscribe(
            ["*"],
            self._store_event,
            sub_id="__store__",
            tenant_filter=None,
        )

        # 4. Service registry
        from .registry.service_registry import ServiceRegistry
        self.registry = ServiceRegistry.get()

        # 5. Workflow engine
        from ..workflow.node_registry     import WorkflowNodeRegistry
        from ..workflow.workflow_engine   import WorkflowEngine
        from ..workflow.action_handlers   import register_builtin_actions
        from ..workflow.event_triggers    import EventTriggerRegistry
        self.node_registry    = WorkflowNodeRegistry.get()
        self.workflow_engine  = WorkflowEngine(self.node_registry)
        register_builtin_actions(self.node_registry)
        self.trigger_registry = EventTriggerRegistry()
        self.trigger_registry.activate(self.event_bus, self.workflow_engine)

        # 6. UI extensions
        from ..ui_extensions.extension_registry import UIExtensionRegistry
        self.ui_registry = UIExtensionRegistry.get()

        # 7. Schema registry
        from ..database.schema_registry import SchemaRegistry
        self.schema_registry = SchemaRegistry.get()

        # 8. Worker pool
        from .workers.worker_pool import WorkerPool
        self.worker_pool = WorkerPool()
        asyncio.create_task(self.worker_pool.run())

        # 9. Lifecycle manager + health monitor + auto recovery
        from .lifecycle.lifecycle_manager import LifecycleManager
        from .lifecycle.health_monitor    import HealthMonitor
        from .lifecycle.auto_recovery     import AutoRecovery
        self.lifecycle_manager = LifecycleManager()
        self.health_monitor    = HealthMonitor(
            lifecycle_manager=self.lifecycle_manager,
            health_dashboard=self.health_dashboard,
        )
        self.auto_recovery = AutoRecovery(
            lifecycle_manager=self.lifecycle_manager,
        )
        asyncio.create_task(self.health_monitor.run())

        # 10. Hot reload watcher
        if self._hot_reload:
            from .loader.hot_reload import HotReloadWatcher
            loader = self._make_loader()
            watcher = HotReloadWatcher(self._plugins_dir, loader=loader)
            asyncio.create_task(watcher.watch())

        self._started = True
        log.info("PlatformRuntime: started")

    # ── Shutdown ──────────────────────────────────────────────────────────

    async def stop(self) -> None:
        if not self._started:
            return
        log.info("PlatformRuntime: stopping …")

        if self.trigger_registry:
            self.trigger_registry.deactivate(self.event_bus)

        if self.worker_pool:
            await self.worker_pool.drain(timeout_s=10.0)

        if self.lifecycle_manager:
            plugin_ids = list(self.lifecycle_manager._plugins.keys())
            for pid in plugin_ids:
                try:
                    await self.lifecycle_manager.stop(pid)
                except Exception:
                    pass

        self._started = False
        log.info("PlatformRuntime: stopped")

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _store_event(self, event: Any) -> None:
        if self.event_store:
            try:
                await self.event_store.append(event)
            except Exception:
                pass

    def _make_loader(self) -> Any:
        from .loader.plugin_loader import PluginLoader
        return PluginLoader(self._plugins_dir)

    def build_context(
        self,
        plugin_id: str,
        tenant_id: str,
        config:    Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Build a ConnectorContext pre-wired with all platform services.
        Called by the lifecycle manager during plugin startup.
        """
        from ..sdk.base_connector import ConnectorContext
        from .adapters.db_adapter      import DBAdapter
        from .adapters.queue_adapter   import QueueAdapter
        from .adapters.webhook_adapter import WebhookAdapter

        db_adapter  = DBAdapter(self._db, plugin_id=plugin_id, tenant_id=tenant_id)
        queue_adapter  = QueueAdapter(self._db)
        webhook_adapter = WebhookAdapter(self._db)

        return ConnectorContext(
            plugin_id=plugin_id,
            tenant_id=tenant_id,
            config=config or {},
            event_bus        =self.event_bus,
            queue            =queue_adapter,
            db               =db_adapter,
            metrics          =self.metrics,
            permissions      =self.permission_engine,
            sandbox          =self.sandbox_manager,
            service_registry =self.registry,
        )
