"""
PluginMetrics — in-process metrics store for the runtime.

Provides increment / gauge / timing operations backed by in-memory
counters.  A Prometheus exporter or DataDog forwarder can be wired by
replacing the FlushBackend.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MetricPoint:
    name:      str
    value:     float
    metric_type: str      # counter | gauge | timing
    plugin_id: str = ""
    tenant_id: str = "__system__"
    tags:      Dict[str, str] = field(default_factory=dict)
    ts:        float = field(default_factory=time.time)


class PluginMetrics:
    """
    Central metrics aggregator for all plugins.

    Accessed via context.metrics (MetricsAdapter wraps this singleton).
    """

    _instance: Optional["PluginMetrics"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "PluginMetrics":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._counters: Dict[str, float]       = defaultdict(float)
        self._gauges:   Dict[str, float]       = {}
        self._timings:  Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()

    # ── Write ─────────────────────────────────────────────────────────────

    def increment(
        self,
        metric: str,
        value: float = 1.0,
        *,
        plugin_id: str = "",
        tenant_id: str = "__system__",
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        key = self._key(metric, plugin_id, tenant_id)
        with self._lock:
            self._counters[key] += value

    def gauge(
        self,
        metric: str,
        value: float,
        *,
        plugin_id: str = "",
        tenant_id: str = "__system__",
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        key = self._key(metric, plugin_id, tenant_id)
        with self._lock:
            self._gauges[key] = value

    def timing(
        self,
        metric: str,
        elapsed_ms: float,
        *,
        plugin_id: str = "",
        tenant_id: str = "__system__",
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        key = self._key(metric, plugin_id, tenant_id)
        with self._lock:
            buf = self._timings[key]
            buf.append(elapsed_ms)
            if len(buf) > 1000:
                del buf[:500]   # keep tail

    # ── Read ──────────────────────────────────────────────────────────────

    def snapshot(
        self,
        plugin_id: str = "",
        tenant_id: str = "__system__",
    ) -> Dict[str, Any]:
        with self._lock:
            prefix = f"{plugin_id}:{tenant_id}:"
            return {
                "counters": {k[len(prefix):]: v for k, v in self._counters.items() if k.startswith(prefix)},
                "gauges":   {k[len(prefix):]: v for k, v in self._gauges.items()   if k.startswith(prefix)},
                "timings":  {
                    k[len(prefix):]: {
                        "count": len(v),
                        "mean":  sum(v) / len(v) if v else 0,
                        "p99":   sorted(v)[int(len(v) * 0.99)] if v else 0,
                    }
                    for k, v in self._timings.items() if k.startswith(prefix)
                },
            }

    def all_counters(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._counters)

    def reset_plugin(self, plugin_id: str, tenant_id: str) -> None:
        prefix = f"{plugin_id}:{tenant_id}:"
        with self._lock:
            for d in (self._counters, self._gauges, self._timings):
                for k in list(d.keys()):
                    if k.startswith(prefix):
                        del d[k]

    @staticmethod
    def _key(metric: str, plugin_id: str, tenant_id: str) -> str:
        return f"{plugin_id}:{tenant_id}:{metric}"
