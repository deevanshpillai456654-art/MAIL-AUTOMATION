"""
MetricsSDK — plugin-safe metrics and counter API.

Usage::

    sdk = MetricsSDK(context)
    sdk.increment("emails.sent")
    sdk.increment("api.calls", tags={"endpoint": "/messages"})
    with sdk.timer("sync.duration"):
        await do_sync()
    sdk.gauge("queue.depth", 42)
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class MetricsSDK:
    """
    Metrics API for plugins.

    Proxied through context.metrics (MetricsAdapter).
    Falls back to in-process counters when no adapter is wired.
    """

    def __init__(self, context: Any) -> None:
        self._ctx = context
        self._local: Dict[str, float] = {}  # fallback in-memory counters

    @property
    def _adapter(self) -> Optional[Any]:
        return getattr(self._ctx, "metrics", None)

    def _plugin_id(self) -> str:
        return getattr(self._ctx, "plugin_id", "unknown")

    def _tenant_id(self) -> str:
        return getattr(self._ctx, "tenant_id", "__system__")

    # ── Counters ──────────────────────────────────────────────────────────

    def increment(
        self,
        metric: str,
        value: float = 1.0,
        *,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Increment a counter metric."""
        if self._adapter and hasattr(self._adapter, "increment"):
            self._adapter.increment(
                metric,
                value,
                plugin_id=self._plugin_id(),
                tenant_id=self._tenant_id(),
                tags=tags or {},
            )
        else:
            key = metric
            self._local[key] = self._local.get(key, 0.0) + value

    def decrement(self, metric: str, value: float = 1.0, *, tags: Optional[Dict[str, str]] = None) -> None:
        self.increment(metric, -value, tags=tags)

    # ── Gauges ────────────────────────────────────────────────────────────

    def gauge(
        self,
        metric: str,
        value: float,
        *,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Set a gauge to an absolute value."""
        if self._adapter and hasattr(self._adapter, "gauge"):
            self._adapter.gauge(
                metric,
                value,
                plugin_id=self._plugin_id(),
                tenant_id=self._tenant_id(),
                tags=tags or {},
            )
        else:
            self._local[metric] = value

    # ── Histograms / Timers ───────────────────────────────────────────────

    def timing(self, metric: str, elapsed_ms: float, *, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a timing value in milliseconds."""
        if self._adapter and hasattr(self._adapter, "timing"):
            self._adapter.timing(
                metric,
                elapsed_ms,
                plugin_id=self._plugin_id(),
                tenant_id=self._tenant_id(),
                tags=tags or {},
            )
        else:
            self._local[f"{metric}.last_ms"] = elapsed_ms

    @contextmanager
    def timer(self, metric: str, *, tags: Optional[Dict[str, str]] = None):
        """Context manager that records elapsed time in milliseconds."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.timing(metric, elapsed_ms, tags=tags)

    # ── Events ────────────────────────────────────────────────────────────

    def event(
        self,
        title: str,
        text: str = "",
        *,
        alert_type: str = "info",
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Emit a named event (e.g. deployment, config change)."""
        if self._adapter and hasattr(self._adapter, "event"):
            self._adapter.event(
                title,
                text,
                alert_type=alert_type,
                plugin_id=self._plugin_id(),
                tenant_id=self._tenant_id(),
                tags=tags or {},
            )

    # ── Snapshot ──────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, float]:
        """Return in-memory counters (useful for testing or debug)."""
        if self._adapter and hasattr(self._adapter, "snapshot"):
            return self._adapter.snapshot(
                plugin_id=self._plugin_id(),
                tenant_id=self._tenant_id(),
            )
        return dict(self._local)

    def reset(self) -> None:
        """Clear in-memory fallback counters."""
        self._local.clear()
