"""
Enterprise Observability System
=================================

Advanced observability:
- Distributed tracing
- Request lineage
- Span correlation
- Provider latency metrics
- Queue analytics
- AI inference profiling
- Websocket telemetry
- System metrics
- Live operational dashboards
"""

import os
import time
import threading
import uuid
import logging
import psutil
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
from collections import deque, defaultdict
from datetime import datetime

logger = logging.getLogger("observability")


class TraceStatus(Enum):
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Span:
    """Trace span"""
    span_id: str
    trace_id: str
    operation: str
    service: str
    start_time: float = field(default_factory=time.time)
    parent_id: Optional[str] = None
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    status: TraceStatus = TraceStatus.STARTED
    tags: Dict[str, str] = field(default_factory=dict)
    logs: List[Dict] = field(default_factory=list)


@dataclass
class Trace:
    """Full trace"""
    trace_id: str
    start_time: float = field(default_factory=time.time)
    spans: List[Span] = field(default_factory=list)
    end_time: Optional[float] = None
    status: TraceStatus = TraceStatus.STARTED


@dataclass
class MetricPoint:
    """Metric data point"""
    name: str
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


class DistributedTracer:
    """Distributed tracing"""
    
    def __init__(self, max_traces: int = 1000):
        self._traces: Dict[str, Trace] = {}
        self._max_traces = max_traces
        self._lock = threading.RLock()
        
        logger.info("Distributed Tracer initialized")
    
    def start_trace(self, operation: str, service: str = "system") -> str:
        """Start new trace"""
        trace_id = str(uuid.uuid4())
        span_id = str(uuid.uuid4())
        
        trace = Trace(trace_id=trace_id, start_time=time.time())
        span = Span(
            span_id=span_id,
            trace_id=trace_id,
            parent_id=None,
            operation=operation,
            service=service,
            start_time=time.time()
        )
        
        trace.spans.append(span)
        
        with self._lock:
            self._traces[trace_id] = trace
            
            # Evict old traces
            if len(self._traces) > self._max_traces:
                oldest = min(self._traces.items(), key=lambda x: x[1].start_time)
                del self._traces[oldest[0]]
        
        return trace_id
    
    def start_span(self, trace_id: str, operation: str, service: str = "system", parent_id: str = None) -> str:
        """Start span in existing trace"""
        span_id = str(uuid.uuid4())
        
        span = Span(
            span_id=span_id,
            trace_id=trace_id,
            parent_id=parent_id,
            operation=operation,
            service=service,
            start_time=time.time()
        )
        
        with self._lock:
            if trace_id in self._traces:
                self._traces[trace_id].spans.append(span)
        
        return span_id
    
    def end_span(self, trace_id: str, span_id: str, status: TraceStatus = TraceStatus.COMPLETED, error: str = None):
        """End span"""
        with self._lock:
            if trace_id not in self._traces:
                return
            
            trace = self._traces[trace_id]
            for span in trace.spans:
                if span.span_id == span_id:
                    span.end_time = time.time()
                    span.duration_ms = (span.end_time - span.start_time) * 1000
                    span.status = status
                    
                    if error:
                        span.tags["error"] = error
                    
                    break
            
            # Check if trace is complete
            all_done = all(s.end_time is not None for s in trace.spans)
            if all_done:
                trace.end_time = time.time()
                trace.status = TraceStatus.COMPLETED
    
    def get_trace(self, trace_id: str) -> Optional[Trace]:
        """Get trace"""
        return self._traces.get(trace_id)
    
    def get_recent_traces(self, limit: int = 10) -> List[Trace]:
        """Get recent traces"""
        with self._lock:
            traces = sorted(
                self._traces.values(),
                key=lambda t: t.start_time,
                reverse=True
            )
            return traces[:limit]


class MetricsCollector:
    """Metrics collection"""
    
    def __init__(self):
        self._metrics: deque = deque(maxlen=10000)
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()
        
        # Start background collection
        self._running = True
        self._thread = threading.Thread(target=self._collect_system_metrics, daemon=True)
        self._thread.start()
    
    def _collect_system_metrics(self):
        """Collect system metrics"""
        while self._running:
            try:
                # CPU
                cpu = psutil.cpu_percent(interval=0.1)
                self.record_gauge("system.cpu.percent", cpu)
                
                # Memory
                mem = psutil.virtual_memory()
                self.record_gauge("system.memory.percent", mem.percent)
                self.record_gauge("system.memory.used_mb", mem.used / (1024*1024))
                
                # Disk
                _disk_root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + os.sep
                disk = psutil.disk_usage(_disk_root)
                self.record_gauge("system.disk.percent", disk.percent)
                
            except Exception as e:
                logger.debug(f"Metrics collection error: {e}")
            
            time.sleep(5)
    
    def record_counter(self, name: str, value: float = 1, labels: Dict[str, str] = None):
        """Record counter"""
        with self._lock:
            self._counters[name] += value
            self._metrics.append(MetricPoint(
                name=name,
                value=value,
                timestamp=time.time(),
                labels=labels or {}
            ))
    
    def record_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record gauge"""
        with self._lock:
            self._gauges[name] = value
            self._metrics.append(MetricPoint(
                name=name,
                value=value,
                timestamp=time.time(),
                labels=labels or {}
            ))
    
    def record_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record histogram value"""
        with self._lock:
            self._histograms[name].append(value)
            # Keep last 1000
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]
            
            self._metrics.append(MetricPoint(
                name=name,
                value=value,
                timestamp=time.time(),
                labels=labels or {}
            ))
    
    def get_counter(self, name: str) -> float:
        """Get counter value"""
        return self._counters.get(name, 0)
    
    def get_gauge(self, name: str) -> Optional[float]:
        """Get gauge value"""
        return self._gauges.get(name)
    
    def get_histogram_stats(self, name: str) -> Dict:
        """Get histogram statistics"""
        values = self._histograms.get(name, [])
        if not values:
            return {}
        
        sorted_vals = sorted(values)
        count = len(sorted_vals)
        
        return {
            "count": count,
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "avg": sum(sorted_vals) / count,
            "p50": sorted_vals[int(count * 0.5)],
            "p95": sorted_vals[int(count * 0.95)],
            "p99": sorted_vals[int(count * 0.99)]
        }
    
    def get_all_metrics(self) -> Dict:
        """Get all metrics"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: self.get_histogram_stats(name)
                    for name in self._histograms.keys()
                }
            }


class ObservabilityEngine:
    """
    Enterprise observability engine.
    """
    
    def __init__(self):
        self.tracer = DistributedTracer()
        self.metrics = MetricsCollector()
        
        # Pre-configured metrics
        self._setup_metrics()
        
        logger.info("Observability Engine initialized")
    
    def _setup_metrics(self):
        """Setup default metrics"""
        # API metrics
        self.metrics.record_gauge("api.requests.total", 0)
        self.metrics.record_gauge("api.errors.total", 0)
        
        # Queue metrics
        self.metrics.record_gauge("queue.events.pending", 0)
        self.metrics.record_gauge("queue.events.processing", 0)
        
        # Provider metrics
        self.metrics.record_gauge("provider.healthy.count", 0)
        self.metrics.record_gauge("provider.isolated.count", 0)
        
        # AI metrics
        self.metrics.record_gauge("ai.inference.total", 0)
        self.metrics.record_gauge("ai.classification.total", 0)
        
        # Memory
        self.metrics.record_gauge("memory.rss_mb", 0)
        
        # Threads
        self.metrics.record_gauge("threads.active", 0)
    
    def record_request(self, endpoint: str, method: str, status: int, duration_ms: float):
        """Record API request"""
        labels = {"endpoint": endpoint, "method": method, "status": str(status)}
        
        self.metrics.record_counter("api.requests.total", 1, labels)
        self.metrics.record_histogram("api.request.duration_ms", duration_ms, labels)
        
        if status >= 400:
            self.metrics.record_counter("api.errors.total", 1, labels)
    
    def record_queue_event(self, topic: str, event: str, queue_size: int):
        """Record queue event"""
        labels = {"topic": topic, "event": event}
        
        self.metrics.record_gauge("queue.events.pending", queue_size, labels)
        
        if event == "enqueued":
            self.metrics.record_counter("queue.enqueue.total", 1, labels)
        elif event == "dequeued":
            self.metrics.record_counter("queue.dequeue.total", 1, labels)
    
    def record_provider_health(self, provider: str, latency_ms: float, success: bool):
        """Record provider health"""
        labels = {"provider": provider}
        
        self.metrics.record_histogram("provider.latency_ms", latency_ms, labels)
        
        if success:
            self.metrics.record_counter("provider.success.total", 1, labels)
        else:
            self.metrics.record_counter("provider.failure.total", 1, labels)
    
    def record_ai_inference(self, model: str, duration_ms: float, confidence: float):
        """Record AI inference"""
        labels = {"model": model}
        
        self.metrics.record_counter("ai.inference.total", 1, labels)
        self.metrics.record_histogram("ai.inference.duration_ms", duration_ms, labels)
        self.metrics.record_histogram("ai.inference.confidence", confidence, labels)
    
    def start_operation(self, operation: str, service: str = "system") -> str:
        """Start traced operation"""
        return self.tracer.start_trace(operation, service)
    
    def end_operation(self, trace_id: str, span_id: str, status: TraceStatus = TraceStatus.COMPLETED, error: str = None):
        """End traced operation"""
        self.tracer.end_span(trace_id, span_id, status, error)
    
    def get_dashboard_data(self) -> Dict:
        """Get dashboard data"""
        metrics = self.metrics.get_all_metrics()
        
        # Get recent traces
        recent_traces = self.tracer.get_recent_traces(5)
        
        # Calculate derived metrics
        api_total = metrics.get("counters", {}).get("api.requests.total", 0)
        api_errors = metrics.get("counters", {}).get("api.errors.total", 0)
        error_rate = (api_errors / api_total * 100) if api_total > 0 else 0
        
        return {
            "timestamp": datetime.now().isoformat(),
            "system": {
                "cpu": metrics.get("gauges", {}).get("system.cpu.percent", 0),
                "memory": metrics.get("gauges", {}).get("system.memory.percent", 0),
                "memory_mb": metrics.get("gauges", {}).get("system.memory.used_mb", 0),
                "disk": metrics.get("gauges", {}).get("system.disk.percent", 0)
            },
            "api": {
                "total_requests": api_total,
                "error_rate": error_rate,
                "latency_p50": metrics.get("histograms", {}).get("api.request.duration_ms", {}).get("p50", 0),
                "latency_p95": metrics.get("histograms", {}).get("api.request.duration_ms", {}).get("p95", 0)
            },
            "ai": {
                "inferences": metrics.get("counters", {}).get("ai.inference.total", 0),
                "avg_confidence": metrics.get("histograms", {}).get("ai.inference.confidence", {}).get("avg", 0)
            },
            "recent_traces": [
                {
                    "trace_id": t.trace_id,
                    "spans": len(t.spans),
                    "status": t.status.value,
                    "duration_ms": (t.end_time - t.start_time) * 1000 if t.end_time else None
                }
                for t in recent_traces
            ]
        }
    
    def get_all_metrics(self) -> Dict:
        """Get all metrics"""
        return self.metrics.get_all_metrics()


# Global observability
_observability: Optional[ObservabilityEngine] = None


def get_observability() -> ObservabilityEngine:
    """Get global observability engine"""
    global _observability
    if _observability is None:
        _observability = ObservabilityEngine()
    return _observability