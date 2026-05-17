"""
LifecycleManager — manages the full plugin lifecycle.

States::

    REGISTERED → STARTING → RUNNING → STOPPING → STOPPED
                     ↓                    ↑
                   FAILED ─────────────────
                     ↓
                  (auto-recovery attempts)

Hooks fired at each transition:
  - on_before_start(plugin_id, context)
  - on_after_start(plugin_id, instance)
  - on_before_stop(plugin_id, instance)
  - on_after_stop(plugin_id)
  - on_failed(plugin_id, error)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

log = logging.getLogger(__name__)


class PluginLifecycleState(str, Enum):
    REGISTERED = "registered"
    STARTING   = "starting"
    RUNNING    = "running"
    STOPPING   = "stopping"
    STOPPED    = "stopped"
    FAILED     = "failed"


@dataclass
class PluginRecord:
    plugin_id:     str
    state:         PluginLifecycleState = PluginLifecycleState.REGISTERED
    instance:      Optional[Any] = None
    started_at:    Optional[str] = None
    stopped_at:    Optional[str] = None
    error:         Optional[str] = None
    start_count:   int = 0
    failure_count: int = 0


LifecycleHook = Callable[..., Coroutine[Any, Any, None]]


class LifecycleManager:
    """
    Manages start/stop/restart for all registered plugins.

    Usage::

        manager = LifecycleManager()
        manager.register("salesforce")
        await manager.start("salesforce", loader=loader, context=ctx)
        await manager.stop("salesforce")
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, PluginRecord] = {}
        self._hooks:   Dict[str, List[LifecycleHook]] = {}
        self._lock     = asyncio.Lock()

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, plugin_id: str) -> None:
        if plugin_id not in self._plugins:
            self._plugins[plugin_id] = PluginRecord(plugin_id=plugin_id)

    def on(self, event: str, hook: LifecycleHook) -> None:
        """Register a lifecycle hook. *event* is e.g. 'after_start', 'failed'."""
        self._hooks.setdefault(event, []).append(hook)

    async def _fire(self, event: str, *args: Any, **kwargs: Any) -> None:
        for hook in self._hooks.get(event, []):
            try:
                await hook(*args, **kwargs)
            except Exception as exc:
                log.error("LifecycleManager: hook '%s' raised: %s", event, exc)

    # ── Start ─────────────────────────────────────────────────────────────

    async def start(
        self,
        plugin_id: str,
        *,
        loader: Any = None,
        context: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        async with self._lock:
            rec = self._plugins.get(plugin_id)
            if not rec:
                self.register(plugin_id)
                rec = self._plugins[plugin_id]
            if rec.state == PluginLifecycleState.RUNNING:
                log.debug("LifecycleManager: %s already running", plugin_id)
                return True
            rec.state = PluginLifecycleState.STARTING

        await self._fire("before_start", plugin_id, context)
        log.info("LifecycleManager: starting %s", plugin_id)

        try:
            instance = None
            if loader:
                loaded = await loader.load(plugin_id)
                if loaded:
                    instance = loaded.get_or_create_instance(
                        context=context,
                        config=config or {},
                    )
                    # Call plugin's startup hook if present
                    startup = getattr(instance, "on_startup", None) or getattr(instance, "start", None)
                    if startup and callable(startup):
                        result = startup()
                        if asyncio.iscoroutine(result):
                            await result

            async with self._lock:
                rec.state     = PluginLifecycleState.RUNNING
                rec.instance  = instance
                rec.started_at = datetime.now(timezone.utc).isoformat()
                rec.start_count += 1
                rec.error      = None

            await self._fire("after_start", plugin_id, instance)
            log.info("LifecycleManager: %s is RUNNING", plugin_id)
            return True

        except Exception as exc:
            async with self._lock:
                rec.state         = PluginLifecycleState.FAILED
                rec.error         = str(exc)
                rec.failure_count += 1
            await self._fire("failed", plugin_id, exc)
            log.error("LifecycleManager: %s failed to start: %s", plugin_id, exc, exc_info=True)
            return False

    # ── Stop ──────────────────────────────────────────────────────────────

    async def stop(self, plugin_id: str) -> bool:
        async with self._lock:
            rec = self._plugins.get(plugin_id)
            if not rec or rec.state not in (
                PluginLifecycleState.RUNNING, PluginLifecycleState.DEGRADED
            ):
                return False
            rec.state = PluginLifecycleState.STOPPING

        await self._fire("before_stop", plugin_id, rec.instance)
        log.info("LifecycleManager: stopping %s", plugin_id)

        try:
            if rec.instance:
                shutdown = (
                    getattr(rec.instance, "on_shutdown", None)
                    or getattr(rec.instance, "stop", None)
                    or getattr(rec.instance, "close", None)
                )
                if shutdown and callable(shutdown):
                    result = shutdown()
                    if asyncio.iscoroutine(result):
                        await result
        except Exception as exc:
            log.warning("LifecycleManager: shutdown hook for %s raised: %s", plugin_id, exc)

        async with self._lock:
            rec.state      = PluginLifecycleState.STOPPED
            rec.stopped_at = datetime.now(timezone.utc).isoformat()
            rec.instance   = None

        await self._fire("after_stop", plugin_id)
        log.info("LifecycleManager: %s is STOPPED", plugin_id)
        return True

    async def restart(self, plugin_id: str, **kwargs: Any) -> bool:
        await self.stop(plugin_id)
        return await self.start(plugin_id, **kwargs)

    async def stop_all(self) -> None:
        for pid in list(self._plugins.keys()):
            await self.stop(pid)

    # ── Status ────────────────────────────────────────────────────────────

    def get_state(self, plugin_id: str) -> Optional[PluginLifecycleState]:
        rec = self._plugins.get(plugin_id)
        return rec.state if rec else None

    def get_instance(self, plugin_id: str) -> Optional[Any]:
        rec = self._plugins.get(plugin_id)
        return rec.instance if rec else None

    def status(self) -> Dict[str, Any]:
        return {
            pid: {
                "state":         rec.state.value,
                "started_at":    rec.started_at,
                "stopped_at":    rec.stopped_at,
                "start_count":   rec.start_count,
                "failure_count": rec.failure_count,
                "error":         rec.error,
            }
            for pid, rec in self._plugins.items()
        }

    def list_running(self) -> List[str]:
        return [
            pid for pid, rec in self._plugins.items()
            if rec.state == PluginLifecycleState.RUNNING
        ]
