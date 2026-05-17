"""
RuntimeAnalytics — aggregated stats across all plugins and tenants.

Collects event counts, error rates, and queue depths for the admin
dashboard.  Backed by PluginMetrics, ErrorTracker, and HealthDashboard.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .metrics         import PluginMetrics
from .error_tracking  import ErrorTracker
from .health_dashboard import HealthDashboard


class RuntimeAnalytics:
    """Read-only analytics rollup over all observability singletons."""

    def __init__(
        self,
        metrics:   Optional[PluginMetrics]   = None,
        errors:    Optional[ErrorTracker]    = None,
        health:    Optional[HealthDashboard] = None,
    ) -> None:
        self._metrics = metrics or PluginMetrics.get()
        self._errors  = errors  or ErrorTracker.get()
        self._health  = health  or HealthDashboard.get()

    def platform_summary(self) -> Dict[str, Any]:
        health    = self._health.summary()
        err_sum   = self._errors.summary()
        counters  = self._metrics.all_counters()

        total_events = sum(v for k, v in counters.items() if "events.published" in k)
        total_errors = sum(s["total"] for s in err_sum.values())

        return {
            "timestamp":    datetime.now(timezone.utc).isoformat(),
            "health":       health["overall"],
            "plugins": {
                "total":   health["total"],
                "healthy": health["healthy"],
                "degraded": health["degraded"],
            },
            "events_published": total_events,
            "total_errors":     total_errors,
            "error_by_plugin":  {pid: s["total"] for pid, s in err_sum.items()},
        }

    def plugin_detail(self, plugin_id: str, tenant_id: str = "__system__") -> Dict[str, Any]:
        return {
            "plugin_id":   plugin_id,
            "tenant_id":   tenant_id,
            "health":      self._health.get_plugin(plugin_id),
            "metrics":     self._metrics.snapshot(plugin_id=plugin_id, tenant_id=tenant_id),
            "recent_errors": self._errors.recent(plugin_id, limit=10),
        }
