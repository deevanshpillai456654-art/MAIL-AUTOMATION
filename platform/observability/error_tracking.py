"""
ErrorTracking — lightweight plugin error capture and aggregation.

Errors are stored in-memory with a ring buffer per plugin.
A future integration (Sentry, Rollbar) can be wired via set_forwarder().
"""
from __future__ import annotations

import threading
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional


@dataclass
class ErrorRecord:
    error_id:  str
    plugin_id: str
    tenant_id: str
    exc_type:  str
    message:   str
    stack:     str
    context:   Dict[str, Any] = field(default_factory=dict)
    ts:        str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ErrorTracker:
    """Ring-buffer error store per plugin."""

    _instance: Optional["ErrorTracker"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "ErrorTracker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self, max_per_plugin: int = 200) -> None:
        self._max     = max_per_plugin
        self._buffers: Dict[str, Deque[ErrorRecord]] = {}
        self._lock    = threading.RLock()
        self._forwarder: Optional[Callable[[ErrorRecord], None]] = None
        self._counter  = 0

    def set_forwarder(self, fn: Callable[[ErrorRecord], None]) -> None:
        self._forwarder = fn

    def capture(
        self,
        exc: Exception,
        *,
        plugin_id: str,
        tenant_id: str = "__system__",
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        self._counter += 1
        error_id = f"err_{self._counter:08d}"
        rec = ErrorRecord(
            error_id=error_id,
            plugin_id=plugin_id,
            tenant_id=tenant_id,
            exc_type=type(exc).__name__,
            message=str(exc),
            stack=traceback.format_exc(),
            context=context or {},
        )
        with self._lock:
            buf = self._buffers.setdefault(plugin_id, deque(maxlen=self._max))
            buf.append(rec)
        if self._forwarder:
            try:
                self._forwarder(rec)
            except Exception:
                pass
        return error_id

    def recent(self, plugin_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            buf = list(self._buffers.get(plugin_id, deque()))[-limit:]
        return [
            {
                "error_id":  r.error_id,
                "exc_type":  r.exc_type,
                "message":   r.message,
                "tenant_id": r.tenant_id,
                "ts":        r.ts,
            }
            for r in reversed(buf)
        ]

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                pid: {"total": len(buf), "latest": buf[-1].ts if buf else None}
                for pid, buf in self._buffers.items()
            }
