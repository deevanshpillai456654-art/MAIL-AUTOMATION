"""
Health Check Aggregator
====================

Aggregates health from multiple sources:
- Component health
- Dependency health
- Custom checks
- Health history
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("health.aggregator")


class HealthLevel(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Health check result"""
    name: str
    level: HealthLevel
    message: str
    duration_ms: float = 0
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class HealthCheckAggregator:
    """
    Aggregates health from multiple sources.
    """

    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._history: deque = deque(maxlen=100)
        self._lock = threading.Lock()

        logger.info("HealthCheckAggregator initialized")

    def register_check(self, name: str, check: Callable):
        """Register health check"""
        self._checks[name] = check

    def run_checks(self) -> Dict[str, HealthCheck]:
        """Run all health checks"""
        results = {}

        for name, check in self._checks.items():
            start = time.time()

            try:
                result = check()

                if isinstance(result, dict):
                    level = HealthLevel(result.get("level", "unknown"))
                    message = result.get("message", "")
                else:
                    level = HealthLevel.HEALTHY if result else HealthLevel.UNHEALTHY
                    message = "OK" if result else "Failed"

                duration_ms = (time.time() - start) * 1000

                results[name] = HealthCheck(
                    name=name,
                    level=level,
                    message=message,
                    duration_ms=duration_ms
                )
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                results[name] = HealthCheck(
                    name=name,
                    level=HealthLevel.UNHEALTHY,
                    message=str(e),
                    duration_ms=duration_ms
                )

        # Store in history
        self._history.append((time.time(), results))

        return results

    def get_overall(self) -> HealthLevel:
        """Get overall health level"""
        results = self.run_checks()

        if not results:
            return HealthLevel.UNKNOWN

        levels = [r.level for r in results.values()]

        if all(l == HealthLevel.HEALTHY for l in levels):
            return HealthLevel.HEALTHY
        elif any(l == HealthLevel.UNHEALTHY for l in levels):
            return HealthLevel.UNHEALTHY
        else:
            return HealthLevel.DEGRADED

    def get_summary(self) -> Dict:
        """Get health summary"""
        results = self.run_checks()
        overall = self.get_overall()

        return {
            "overall": overall.value,
            "total": len(results),
            "healthy": sum(1 for r in results.values() if r.level == HealthLevel.HEALTHY),
            "degraded": sum(1 for r in results.values() if r.level == HealthLevel.DEGRADED),
            "unhealthy": sum(1 for r in results.values() if r.level == HealthLevel.UNHEALTHY),
            "checks": {
                name: {"level": r.level.value, "message": r.message}
                for name, r in results.items()
            }
        }


# Global aggregator
_aggregator: Optional[HealthCheckAggregator] = None


def get_health_aggregator() -> HealthCheckAggregator:
    """Get global health aggregator"""
    global _aggregator
    if _aggregator is None:
        _aggregator = HealthCheckAggregator()
    return _aggregator


__all__ = ["HealthCheckAggregator", "HealthCheck", "HealthLevel", "get_health_aggregator"]
