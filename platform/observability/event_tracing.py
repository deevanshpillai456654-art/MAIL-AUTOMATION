"""
EventTracing — distributed trace correlation across plugin event chains.

Each outbound event carries a trace_id.  The tracer records span entries
so the full causal chain can be reconstructed.
"""
from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class TraceSpan:
    span_id:    str
    trace_id:   str
    plugin_id:  str
    tenant_id:  str
    operation:  str
    started_at: str
    finished_at: Optional[str] = None
    status:     str = "ok"   # ok | error
    metadata:   Dict[str, Any] = field(default_factory=dict)

    def finish(self, *, status: str = "ok", **metadata: Any) -> None:
        self.finished_at = datetime.now(timezone.utc).isoformat()
        self.status = status
        self.metadata.update(metadata)


class EventTracer:
    """
    Lightweight in-process tracer.

    Keeps up to max_spans spans per trace_id in a ring buffer.
    """

    _instance: Optional["EventTracer"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "EventTracer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self, max_spans: int = 500) -> None:
        self._traces: Dict[str, List[TraceSpan]] = defaultdict(list)
        self._max    = max_spans
        self._lock   = threading.RLock()

    def start_span(
        self,
        operation:  str,
        *,
        trace_id:   Optional[str] = None,
        plugin_id:  str = "unknown",
        tenant_id:  str = "__system__",
        **metadata: Any,
    ) -> TraceSpan:
        tid = trace_id or str(uuid.uuid4())
        span = TraceSpan(
            span_id=str(uuid.uuid4()),
            trace_id=tid,
            plugin_id=plugin_id,
            tenant_id=tenant_id,
            operation=operation,
            started_at=datetime.now(timezone.utc).isoformat(),
            metadata=dict(metadata),
        )
        with self._lock:
            buf = self._traces[tid]
            buf.append(span)
            if len(buf) > self._max:
                del buf[:self._max // 2]
        return span

    def get_trace(self, trace_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            spans = list(self._traces.get(trace_id, []))
        return [self._span_dict(s) for s in spans]

    def recent_traces(self, limit: int = 20) -> List[str]:
        with self._lock:
            return list(self._traces.keys())[-limit:]

    @staticmethod
    def _span_dict(s: TraceSpan) -> Dict[str, Any]:
        return {
            "span_id":     s.span_id,
            "trace_id":    s.trace_id,
            "plugin_id":   s.plugin_id,
            "operation":   s.operation,
            "started_at":  s.started_at,
            "finished_at": s.finished_at,
            "status":      s.status,
            "metadata":    s.metadata,
        }
