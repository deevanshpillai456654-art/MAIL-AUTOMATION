import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from backend import config
from .event_bus_durable import EventBusCore
from .event_store import DurableEventStore
from .resource_manager import ResourceManager, ResourceThresholds
from .provider_isolation import ProviderIsolator, ProviderQuota, ProviderTask
from .crash_recovery import CrashRecoveryEngine
from .startup_orchestrator import StartupOrchestrator, DependencyLevel
from .streaming import StreamingPipeline
from .observability import DistributedTracer, MetricsCollector
from .oauth_security import OAuthSessionManager
from .security_zones import SecurityZoneEnforcer
from backend.sync.gmail_sync import sync_gmail_account
from backend.sync.imap_sync import sync_imap_account
from backend.sync.outlook_sync import sync_outlook_account
from backend.core.provider_capability_registry import ProviderCapabilityRegistry

GLOBAL_ENTERPRISE_SYSTEM: Optional["EnterpriseSystem"] = None

logger = logging.getLogger("enterprise.system")


class EnterpriseSystem:
    """Enterprise-grade system coordinator for core services."""

    def __init__(self):
        self.data_dir = Path(config.DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.event_bus = EventBusCore(
            db_path=str(self.data_dir / "eventbus.db"),
            max_queue_size=10000,
            worker_count=config.MAX_WORKERS,
            enable_persistence=True
        )

        self.event_store = DurableEventStore()
        self.resource_manager = ResourceManager(thresholds=ResourceThresholds())
        self.provider_isolator = ProviderIsolator()
        for provider in ["gmail", "outlook", "yahoo", "zoho", "imap", "exchange"]:
            self.provider_isolator.register_provider(provider)
        self.crash_recovery = CrashRecoveryEngine()
        self.startup_orchestrator = StartupOrchestrator()
        self.streaming_pipeline = StreamingPipeline()
        self.tracer = DistributedTracer()
        self.metrics = MetricsCollector()
        self.oauth_manager = OAuthSessionManager()
        self.security_zones = SecurityZoneEnforcer()

        self._started = False

        logger.info("EnterpriseSystem initialized")

    def submit_provider_task(self, provider: str, action: str, func: Callable, args: Optional[list] = None, kwargs: Optional[dict] = None, idempotency_key: str = None, metadata: Optional[dict] = None) -> bool:
        """Submit a provider task to the isolation queue."""
        args = args or []
        kwargs = kwargs or {}
        metadata = metadata or {}
        task = ProviderTask(
            task_id=secrets.token_hex(10),
            provider=provider,
            action=action,
            func=func,
            args=args,
            kwargs=kwargs,
            idempotency_key=idempotency_key,
            metadata=metadata
        )

        if not self.provider_isolator.is_available(provider):
            logger.warning(f"Provider task submission failed, provider unavailable: {provider}")
            return False

        enqueued = self.provider_isolator.enqueue_task(provider, task)
        if enqueued:
            self.event_bus.publish("provider.task.enqueued", {
                "task_id": task.task_id,
                "provider": provider,
                "action": action,
                "metadata": metadata,
                "created_at": task.created_at
            })
        return enqueued

    def _get_sync_callable(self, provider: str):
        provider = ProviderCapabilityRegistry.normalize(provider)
        if provider == "gmail":
            return sync_gmail_account
        if provider in {"outlook", "microsoft365", "exchange"}:
            return sync_outlook_account
        capability = ProviderCapabilityRegistry().get(provider)
        if capability.supports_imap:
            return sync_imap_account
        return None

    def queue_provider_sync(self, account_id: int, provider: str, max_results: int = 50, sync_id: int = None, metadata: Optional[dict] = None) -> bool:
        """Queue a sync request for a provider account."""
        sync_callable = self._get_sync_callable(provider)
        if not sync_callable:
            logger.warning(f"No sync callable available for provider: {provider}")
            return False

        return self.submit_provider_task(
            provider,
            "sync",
            sync_callable,
            args=[account_id, max_results, sync_id],
            metadata=metadata or {"source": "enterprise.queue"}
        )

    def _handle_provider_sync_request(self, event: Any):
        payload = event.payload or {}
        account_id = payload.get("account_id")
        provider = payload.get("provider")
        max_results = payload.get("max_results", 50)
        sync_id = payload.get("sync_id")
        if not account_id or not provider:
            logger.warning("Sync request event missing account_id or provider")
            return

        sync_callable = self._get_sync_callable(provider)
        if not sync_callable:
            logger.warning(f"No sync handler for provider: {provider}")
            return

        self.submit_provider_task(
            provider,
            "sync",
            sync_callable,
            args=[account_id, max_results, sync_id],
            metadata={"event": "provider.sync.request"}
        )

    def _on_provider_task_start(self, task: ProviderTask):
        self.event_bus.publish("provider.task.started", {
            "task_id": task.task_id,
            "provider": task.provider,
            "action": task.action,
            "created_at": task.created_at
        })

    def _on_provider_task_success(self, task: ProviderTask, result: Any):
        self.event_bus.publish("provider.task.completed", {
            "task_id": task.task_id,
            "provider": task.provider,
            "action": task.action,
            "result": result
        })

    def _on_provider_task_failure(self, task: ProviderTask, error: str):
        self.event_bus.publish("provider.task.failed", {
            "task_id": task.task_id,
            "provider": task.provider,
            "action": task.action,
            "error": error,
            "retries": task.retries
        })

    def start(self):
        if self._started:
            return

        logger.info("Starting EnterpriseSystem components")

        self.resource_manager.start()
        self.streaming_pipeline.start()
        self.provider_isolator.start_workers()
        self.provider_isolator.on_task_callbacks(
            on_task_start=self._on_provider_task_start,
            on_task_success=self._on_provider_task_success,
            on_task_failure=self._on_provider_task_failure
        )
        self.event_bus.subscribe("provider.sync.request", self._handle_provider_sync_request, group_id="sync-workers")
        self._register_components()
        self._started = True
        logger.info("EnterpriseSystem started")

    def shutdown(self):
        logger.info("Shutting down EnterpriseSystem")
        try:
            self.streaming_pipeline.stop()
        except Exception as exc:
            logger.warning(f"Streaming pipeline shutdown error: {exc}")

        try:
            self.provider_isolator.stop_workers()
        except Exception as exc:
            logger.warning(f"Provider isolator shutdown error: {exc}")

        try:
            self.resource_manager.stop()
        except Exception as exc:
            logger.warning(f"Resource manager shutdown error: {exc}")

        try:
            self.event_bus.shutdown()
        except Exception as exc:
            logger.warning(f"Event bus shutdown error: {exc}")

        self._started = False
        logger.info("EnterpriseSystem shutdown complete")

    def _register_components(self):
        self.startup_orchestrator.register_component(
            name="database",
            level=DependencyLevel.CORE,
            dependencies=[],
            start_func=self._noop_start,
            health_check=self._health_check_database,
            timeout=20.0,
            retry_count=2
        )

        self.startup_orchestrator.register_component(
            name="event_bus",
            level=DependencyLevel.CORE,
            dependencies=["database"],
            start_func=self._noop_start,
            health_check=self._health_check_event_bus,
            timeout=20.0,
            retry_count=2
        )

        self.startup_orchestrator.register_component(
            name="provider_isolator",
            level=DependencyLevel.SERVICES,
            dependencies=["event_bus"],
            start_func=self._noop_start,
            health_check=self._health_check_provider_isolator,
            timeout=20.0,
            retry_count=2
        )

        self.startup_orchestrator.register_component(
            name="resource_manager",
            level=DependencyLevel.CORE,
            dependencies=["database"],
            start_func=self._noop_start,
            health_check=self._health_check_resource_manager,
            timeout=20.0,
            retry_count=2
        )

        self.startup_orchestrator.register_component(
            name="streaming_pipeline",
            level=DependencyLevel.APPLICATION,
            dependencies=["event_bus", "resource_manager"],
            start_func=self._noop_start,
            health_check=self._health_check_streaming_pipeline,
            timeout=20.0,
            retry_count=2
        )

    def _noop_start(self):
        return True

    def _health_check_database(self) -> bool:
        return Path(config.DB_PATH).exists()

    def _health_check_event_bus(self) -> bool:
        return bool(self.event_bus)

    def _health_check_provider_isolator(self) -> bool:
        return self.provider_isolator.is_available("gmail") or self.provider_isolator.is_available("outlook")

    def _health_check_resource_manager(self) -> bool:
        return self.resource_manager.current_state in {self.resource_manager.current_state.NORMAL, self.resource_manager.current_state.WARNING}

    def _health_check_streaming_pipeline(self) -> bool:
        return bool(self.streaming_pipeline)

    def get_status(self) -> Dict[str, Any]:
        return {
            "started": self._started,
            "event_bus": {
                "stats": self.event_bus.get_stats(),
                "persistence": self.event_bus.enable_persistence
            },
            "resource_manager": {
                "state": self.resource_manager.current_state.value,
                "throttle_factor": self.resource_manager._throttle_factor
            },
            "provider_isolation": {
                "registered_providers": list(self.provider_isolator._providers.keys()),
                "provider_states": {
                    provider: {
                        "state": state.state.value,
                        "error_count": state.error_count,
                        "success_count": state.success_count,
                        "last_error": state.last_error,
                        "avg_latency_ms": state.avg_latency_ms,
                        "reconnect_count": state.reconnect_count,
                        "isolation_level": state.isolation_level.value
                    }
                    for provider, state in self.provider_isolator._providers.items()
                }
            },
            "startup": {
                "components": list(self.startup_orchestrator._components.keys())
            },
            "streaming": {
                "active_streams": len(self.streaming_pipeline.registry._streams)
            }
        }

    def get_diagnostics(self) -> Dict[str, Any]:
        return {
            "resource_history": list(self.resource_manager._memory_history),
            "cpu_history": list(self.resource_manager._cpu_history),
            "recent_traces": [trace.trace_id for trace in self.tracer.get_recent_traces(5)]
        }
