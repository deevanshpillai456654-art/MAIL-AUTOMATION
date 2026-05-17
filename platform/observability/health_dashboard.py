"""
HealthDashboard — aggregates health check results across all plugins.

Queries each registered plugin's health_check() periodically (via
HealthMonitor) and exposes a summary dict suitable for a /health endpoint.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class HealthDashboard:
    """
    Stores the latest health check result per plugin and exposes a
    rolled-up status for the platform.
    """

    _instance: Optional["HealthDashboard"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "HealthDashboard":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._results: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def update(self, plugin_id: str, result: Dict[str, Any]) -> None:
        """Called by HealthMonitor after each health_check() call."""
        with self._lock:
            self._results[plugin_id] = {
                **result,
                "plugin_id":   plugin_id,
                "checked_at":  datetime.now(timezone.utc).isoformat(),
            }

    def get_plugin(self, plugin_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._results.get(plugin_id)

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            results = dict(self._results)

        healthy  = [p for p, r in results.items() if r.get("healthy")]
        degraded = [p for p, r in results.items() if not r.get("healthy")]

        return {
            "overall":  "healthy" if not degraded else ("degraded" if healthy else "unhealthy"),
            "total":    len(results),
            "healthy":  len(healthy),
            "degraded": len(degraded),
            "plugins":  results,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def all_results(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._results.values())
