"""
HealthMonitor — periodic health checks for all running plugins.

Publishes `plugin.health.ok` / `plugin.health.degraded` / `plugin.health.failed`
events through the runtime event bus.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    plugin_id:   str
    healthy:     bool
    latency_ms:  Optional[float] = None
    message:     str = ""
    checked_at:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details:     Dict[str, Any] = field(default_factory=dict)


class HealthMonitor:
    """
    Runs health checks on all registered plugins at a configurable interval.

    Usage::

        monitor = HealthMonitor(
            lifecycle_manager=lm,
            bus=get_runtime_bus(),
            interval_s=30,
        )
        asyncio.create_task(monitor.run())
    """

    def __init__(
        self,
        lifecycle_manager: Any,
        bus: Any,
        interval_s: float = 30.0,
        timeout_s: float = 10.0,
    ) -> None:
        self._lifecycle = lifecycle_manager
        self._bus       = bus
        self._interval  = interval_s
        self._timeout   = timeout_s
        self._results:  Dict[str, HealthCheckResult] = {}
        self._running   = False

    async def run(self) -> None:
        self._running = True
        log.info("HealthMonitor: started, interval=%.0fs", self._interval)
        while self._running:
            await asyncio.sleep(self._interval)
            await self.check_all()

    async def check_all(self) -> List[HealthCheckResult]:
        running = self._lifecycle.list_running()
        tasks = [self._check_one(pid) for pid in running]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = []
        for r in results:
            if isinstance(r, HealthCheckResult):
                out.append(r)
        return out

    async def _check_one(self, plugin_id: str) -> Optional[HealthCheckResult]:
        instance = self._lifecycle.get_instance(plugin_id)
        if not instance:
            return None

        checker = getattr(instance, "health_check", None)
        if not callable(checker):
            # No health check defined → assume healthy
            result = HealthCheckResult(plugin_id=plugin_id, healthy=True, message="no_check")
            self._results[plugin_id] = result
            return result

        import time
        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(checker(), timeout=self._timeout)
            latency = (time.monotonic() - t0) * 1000
            healthy = raw.get("healthy", True) if isinstance(raw, dict) else bool(raw)
            result = HealthCheckResult(
                plugin_id=plugin_id,
                healthy=healthy,
                latency_ms=round(latency, 1),
                message=raw.get("message", "") if isinstance(raw, dict) else "",
                details=raw if isinstance(raw, dict) else {},
            )
        except asyncio.TimeoutError:
            result = HealthCheckResult(
                plugin_id=plugin_id, healthy=False, message="timeout"
            )
        except Exception as exc:
            result = HealthCheckResult(
                plugin_id=plugin_id, healthy=False, message=str(exc)
            )

        self._results[plugin_id] = result

        if self._bus:
            event_type = (
                "plugin.health.ok" if result.healthy
                else "plugin.health.degraded"
            )
            try:
                await self._bus.publish(
                    event_type,
                    source="health_monitor",
                    tenant_id="__system__",
                    payload={
                        "plugin_id":  plugin_id,
                        "healthy":    result.healthy,
                        "latency_ms": result.latency_ms,
                        "message":    result.message,
                    },
                )
            except Exception:
                pass

        if not result.healthy:
            log.warning("HealthMonitor: %s unhealthy — %s", plugin_id, result.message)

        return result

    def last_result(self, plugin_id: str) -> Optional[HealthCheckResult]:
        return self._results.get(plugin_id)

    def summary(self) -> Dict[str, Any]:
        healthy   = sum(1 for r in self._results.values() if r.healthy)
        unhealthy = len(self._results) - healthy
        return {
            "checked":  len(self._results),
            "healthy":  healthy,
            "unhealthy": unhealthy,
            "plugins":  {
                pid: {"healthy": r.healthy, "latency_ms": r.latency_ms, "message": r.message}
                for pid, r in self._results.items()
            },
        }

    def stop(self) -> None:
        self._running = False
