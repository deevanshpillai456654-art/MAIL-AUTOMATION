"""
Metrics Exporter - Prometheus Export
==============================

Prometheus metrics exporting:
- Counter metrics
- Gauge metrics
- Histogram metrics
- Summary metrics
- Custom collectors
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("metrics.exporter")


@dataclass
class CounterMetric:
    """Counter metric"""
    name: str
    value: float = 0
    labels: Dict[str, str] = field(default_factory=dict)
    last_update: float = field(default_factory=time.time)


@dataclass
class GaugeMetric:
    """Gauge metric"""
    name: str
    value: float = 0
    labels: Dict[str, str] = field(default_factory=dict)
    last_update: float = field(default_factory=time.time)


@dataclass
class HistogramMetric:
    """Histogram metric"""
    name: str
    values: List[float] = field(default_factory=list)
    buckets: List[float] = field(default_factory=lambda: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0])
    count: int = 0
    sum: float = 0


class PrometheusExporter:
    """
    Prometheus metrics exporter.
    """

    def __init__(self):
        self._counters: Dict[str, CounterMetric] = {}
        self._gauges: Dict[str, GaugeMetric] = {}
        self._histograms: Dict[str, HistogramMetric] = {}
        self._lock = threading.Lock()

        logger.info("PrometheusExporter initialized")

    def counter(self, name: str, value: float = 1, labels: Dict = None):
        """Increment counter"""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = CounterMetric(name=name, labels=labels or {})

            self._counters[name].value += value
            self._counters[name].last_update = time.time()

    def gauge(self, name: str, value: float, labels: Dict = None):
        """Set gauge"""
        with self._lock:
            self._gauges[name] = GaugeMetric(
                name=name,
                value=value,
                labels=labels or {},
                last_update=time.time()
            )

    def histogram(self, name: str, value: float):
        """Observe histogram"""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = HistogramMetric(name=name)

            h = self._histograms[name]
            h.values.append(value)
            if len(h.values) > 1000:
                h.values = h.values[-1000:]
            h.count += 1
            h.sum += value

    def export(self) -> str:
        """Export metrics in Prometheus format"""
        lines = []

        with self._lock:
            # Counters
            for m in self._counters.values():
                labels = ",".join(f'{k}="{v}"' for k, v in m.labels.items())
                if labels:
                    lines.append(f"{m.name}{{{labels}}} {m.value}")
                else:
                    lines.append(f"{m.name} {m.value}")

            # Gauges
            for m in self._gauges.values():
                labels = ",".join(f'{k}="{v}"' for k, v in m.labels.items())
                if labels:
                    lines.append(f"{m.name}{{{labels}}} {m.value}")
                else:
                    lines.append(f"{m.name} {m.value}")

            # Histograms
            for m in self._histograms.values():
                # Bucket summary
                lines.append(f"{m.name}_count {m.count}")
                lines.append(f"{m.name}_sum {m.sum}")

        return "\n".join(lines)

    def get_stats(self) -> Dict:
        """Get exporter stats"""
        with self._lock:
            return {
                "counters": len(self._counters),
                "gauges": len(self._gauges),
                "histograms": len(self._histograms)
            }


# Global exporter
_exporter: Optional[PrometheusExporter] = None


def get_exporter() -> PrometheusExporter:
    """Get global exporter"""
    global _exporter
    if _exporter is None:
        _exporter = PrometheusExporter()
    return _exporter


# Convenience functions
def increment_counter(name: str, value: float = 1, labels: Dict = None):
    """Increment counter metric"""
    get_exporter().counter(name, value, labels)


def set_gauge(name: str, value: float, labels: Dict = None):
    """Set gauge metric"""
    get_exporter().gauge(name, value, labels)


def observe_histogram(name: str, value: float):
    """Observe histogram value"""
    get_exporter().histogram(name, value)


__all__ = ["PrometheusExporter", "increment_counter", "set_gauge", "observe_histogram", "get_exporter"]
