"""
System Metrics - Performance Monitoring
==========================================

Centralized metrics collection and reporting.
"""

import time
import threading
import psutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import defaultdict, deque
from datetime import datetime


@dataclass
class MetricSample:
    """A single metric sample"""
    name: str
    value: float
    timestamp: float
    labels: Dict[str, str] = field(default_factory=dict)


class MetricsRegistry:
    """Thread-safe metrics registry"""
    
    def __init__(self, max_samples: int = 10000):
        self._samples: deque = deque(maxlen=max_samples)
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
    
    def record(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record a metric sample"""
        with self._lock:
            self._samples.append(MetricSample(
                name=name,
                value=value,
                timestamp=time.time(),
                labels=labels or {}
            ))
            
            # Update histogram
            if name in self._histograms:
                self._histograms[name].append(value)
                if len(self._histograms[name]) > 1000:
                    self._histograms[name] = self._histograms[name][-1000:]
    
    def increment(self, name: str, value: int = 1):
        """Increment a counter"""
        with self._lock:
            self._counters[name] += value
    
    def gauge(self, name: str, value: float):
        """Set a gauge value"""
        with self._lock:
            self._gauges[name] = value
    
    def histogram(self, name: str, value: float):
        """Record histogram value"""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
    
    def get_counter(self, name: str) -> int:
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
        
        sorted_values = sorted(values)
        return {
            "count": len(values),
            "sum": sum(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "p50": sorted_values[len(sorted_values) // 2],
            "p95": sorted_values[int(len(sorted_values) * 0.95)],
            "p99": sorted_values[int(len(sorted_values) * 0.99)]
        }
    
    def get_all_metrics(self) -> Dict:
        """Get all metrics"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    name: self.get_histogram_stats(name)
                    for name in self._histograms
                },
                "sample_count": len(self._samples)
            }


# Global metrics registry
_metrics_registry: Optional[MetricsRegistry] = None


def get_metrics() -> MetricsRegistry:
    """Get global metrics registry"""
    global _metrics_registry
    if _metrics_registry is None:
        _metrics_registry = MetricsRegistry()
    return _metrics_registry


# Pre-defined metrics helpers
def record_emailclassified(category: str):
    """Record email classification"""
    get_metrics().increment(f"email_classified_total")
    get_metrics().increment(f"email_classified_{category}")


def record_sync_operation(provider: str, status: str):
    """Record sync operation"""
    get_metrics().increment(f"sync_total")
    get_metrics().increment(f"sync_{provider}_{status}")


def record_api_request(method: str, endpoint: str, status: int):
    """Record API request"""
    get_metrics().increment(f"api_requests_total")
    get_metrics().increment(f"api_{method}_{endpoint}")
    get_metrics().increment(f"api_status_{status}")


def record_oauth_flow(provider: str, status: str):
    """Record OAuth flow"""
    get_metrics().increment(f"oauth_{provider}_{status}")


def set_memory_usage():
    """Record current memory usage"""
    mem = psutil.virtual_memory()
    get_metrics().gauge("memory_percent", mem.percent)
    get_metrics().gauge("memory_used_mb", mem.used / (1024*1024))


def set_cpu_usage():
    """Record current CPU usage"""
    cpu = psutil.cpu_percent(interval=0.1)
    get_metrics().gauge("cpu_percent", cpu)


# Export convenience functions
__all__ = [
    "MetricsRegistry",
    "MetricSample",
    "get_metrics",
    "record_email_classified",
    "record_sync_operation",
    "record_api_request",
    "record_oauth_flow",
    "set_memory_usage",
    "set_cpu_usage"
]