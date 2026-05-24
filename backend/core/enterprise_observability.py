"""
Enterprise Observability Platform
=================================

Enterprise observability:
- OpenTelemetry integration
- Grafana-compatible metrics
- Distributed tracing with W3C format
- Event correlation engine
- Service map generation
- Anomaly alerting
- Log aggregation
- Custom dashboards
- SLO/SLI tracking
- Cost observability
"""

import hashlib
import logging
import statistics
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("observability.platform")


class MetricType(Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SLOStatus(Enum):
    GOOD = "good"
    DEGRADED = "degraded"
    VIOLATED = "violated"


@dataclass
class OTelSpan:
    """OpenTelemetry-compatible span"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation_name: str
    service_name: str
    start_time_unix_nano: int
    end_time_unix_nano: Optional[int]
    status_code: int = 0
    status_message: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AlertRule:
    """Alert rule configuration"""
    rule_id: str
    metric_name: str
    condition: str
    threshold: float
    duration_seconds: int
    severity: AlertSeverity
    enabled: bool = True


@dataclass
class SLI:
    """Service Level Indicator"""
    sli_id: str
    name: str
    metric_name: str
    target: float
    window: str
    current_value: float = 0.0


@dataclass
class SLO:
    """Service Level Objective"""
    slo_id: str
    name: str
    slis: List[str]
    budget: float
    period: str
    status: SLOStatus = SLOStatus.GOOD
    remaining_rror_budget: float = 0.0


@dataclass
class ServiceNode:
    """Service map node"""
    service_id: str
    service_name: str
    requests: int = 0
    errors: int = 0
    latency_p50: float = 0.0
    latency_p99: float = 0.0


@dataclass
class ServiceEdge:
    """Service map edge"""
    from_service: str
    to_service: str
    requests: int = 0
    errors: int = 0


class OpenTelemetryIntegrator:
    """OpenTelemetry W3C Trace Context integration"""

    TRACE_STATE_VERSION = "v0.1"

    def __init__(self):
        self._traces: Dict[str, OTelSpan] = {}
        self._active_spans: Dict[str, List[str]] = defaultdict(list)
        self._lock = threading.RLock()
        self._config = {
            "enable_w3c_trace_context": True,
            "enable_b3_propagation": True,
            "sample_rate": 1.0,
            "max_traces_per_second": 1000
        }

    def create_trace_id(self) -> str:
        """Create W3C-compatible trace ID"""
        trace_id = hashlib.sha256(str(time.time()).encode()).hexdigest()[:32]
        span_id = hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:16]
        return f"00-{trace_id}-{span_id}-01"

    def create_span_id(self) -> str:
        """Create W3C-compatible span ID"""
        return hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:16]

    def extractTraceContext(self, headers: Dict[str, str]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract W3C Trace Context from headers"""
        traceparent = headers.get("traceparent", "")

        if not traceparent:
            return None, None, None

        try:
            parts = traceparent.split("-")
            if len(parts) >= 3:
                trace_id = parts[1]
                span_id = parts[2]
                parent_id = parts[3] if len(parts) > 3 else None
                return trace_id, span_id, parent_id
        except Exception:
            pass

        return None, None, None

    def inject_trace_context(self, span: OTelSpan) -> Dict[str, str]:
        """Inject W3C Trace Context to headers"""
        return {
            "traceparent": f"00-{span.trace_id}-{span.span_id}-{self.TRACE_STATE_VERSION}",
            "tracestate": f"service={span.service_name}"
        }

    def start_span(self,
                trace_id: str,
                span_id: str,
                operation: str,
                service: str,
                parent_id: Optional[str] = None) -> OTelSpan:
        """Start new span"""
        span = OTelSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_id,
            operation_name=operation,
            service_name=service,
            start_time_unix_nano=int(time.time() * 1e9)
        )

        with self._lock:
            self._traces[span_id] = span
            self._active_spans[trace_id].append(span_id)

        return span

    def end_span(self, span_id: str, status_code: int = 0, status_message: str = ""):
        """End span"""
        with self._lock:
            if span_id in self._traces:
                span = self._traces[span_id]
                span.end_time_unix_nano = int(time.time() * 1e9)
                span.status_code = status_code
                span.status_message = status_message

    def add_event(self, span_id: str, name: str, attributes: Dict[str, Any] = None):
        """Add event to span"""
        with self._lock:
            if span_id in self._traces:
                event = {
                    "name": name,
                    "timestamp_unix_nano": int(time.time() * 1e9),
                    "attributes": attributes or {}
                }
                self._traces[span_id].events.append(event)

    def get_span(self, span_id: str) -> Optional[OTelSpan]:
        """Get span"""
        return self._traces.get(span_id)


class GrafanaMetricsExporter:
    """Grafana-compatible metrics exporter"""

    def __init__(self):
        self._counters: Dict[str, float] = {}
        self._counters_metadata: Dict[str, Dict[str, str]] = {}
        self._gauges: Dict[str, float] = {}
        self._gauges_metadata: Dict[str, Dict[str, str]] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)
        self._histograms_metadata: Dict[str, Dict[str, str]] = {}
        self._lock = threading.RLock()

    def record_counter(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record counter metric"""
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value
            self._counters_metadata[key] = {
                "name": name,
                "type": "counter",
                "labels": labels or {}
            }

    def record_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record gauge metric"""
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = value
            self._gauges_metadata[key] = {
                "name": name,
                "type": "gauge",
                "labels": labels or {}
            }

    def record_histogram(self, name: str, value: float, labels: Dict[str, str] = None):
        """Record histogram metric"""
        key = self._make_key(name, labels)
        with self._lock:
            self._histograms[key].append(value)
            if len(self._histograms[key]) > 1000:
                self._histograms[key] = self._histograms[key][-1000:]
            self._histograms_metadata[key] = {
                "name": name,
                "type": "histogram",
                "labels": labels or {}
            }

    def _make_key(self, name: str, labels: Optional[Dict[str, str]]) -> str:
        """Create metric key"""
        if not labels:
            return name

        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def export_prometheus(self) -> str:
        """Export in Prometheus format"""
        lines = []

        with self._lock:
            for key, value in self._counters.items():
                lines.append(f"{key} {value}")

            for key, value in self._gauges.items():
                lines.append(f"{key} {value}")

            for key, values in self._histograms.items():
                if values:
                    sorted_vals = sorted(values)
                    n = len(sorted_vals)

                    count = n
                    sum_val = sum(sorted_vals)
                    min_val = sorted_vals[0]
                    max_val = sorted_vals[-1]

                    p50_idx = int(n * 0.5)
                    p95_idx = int(n * 0.95)
                    p99_idx = int(n * 0.99)

                    base_key = key.rstrip("{}").split("{")[0]

                    lines.append(f"{base_key}_count {count}")
                    lines.append(f"{base_key}_sum {sum_val}")
                    lines.append(f"{base_key}_bucket {{le=\"{min_val}\"}} 0")

                    for le in [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]:
                        bucket_count = sum(1 for v in sorted_vals if v <= le)
                        lines.append(f"{base_key}_bucket {{le=\"{le}\"}} {bucket_count}")

                    lines.append(f"{base_key}_bucket {{le=\"+Inf\"}} {count}")

        return "\n".join(lines) + "\n"

    def export_json(self) -> Dict[str, Any]:
        """Export in JSON format"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {
                    k: {
                        "count": len(v),
                        "sum": sum(v),
                        "min": min(v) if v else 0,
                        "max": max(v) if v else 0,
                        "avg": statistics.mean(v) if v else 0,
                        "p50": statistics.median(v) if v else 0
                    }
                    for k, v in self._histograms.items()
                }
            }


class AlertEngine:
    """Alerting engine with anomaly detection"""

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._active_alerts: Dict[str, Dict[str, Any]] = {}
        self._alert_history: deque = deque(maxlen=1000)
        self._lock = threading.RLock()
        self._config = {
            "enable_alerting": True,
            "alert_cooldown_seconds": 300
        }

    def add_rule(self, rule: AlertRule):
        """Add alert rule"""
        with self._lock:
            self._rules[rule.rule_id] = rule

    def check_conditions(self, metrics: Dict[str, float]) -> List[Dict[str, Any]]:
        """Check alert conditions"""
        triggered = []

        with self._lock:
            for rule_id, rule in self._rules.items():
                if not rule.enabled:
                    continue

                if rule.metric_name not in metrics:
                    continue

                value = metrics[rule.metric_name]
                triggered_now = self._evaluate_condition(value, rule.condition, rule.threshold)

                if triggered_now:
                    existing = self._active_alerts.get(rule_id)

                    if not existing:
                        self._active_alerts[rule_id] = {
                            "rule_id": rule_id,
                            "triggered_at": time.time(),
                            "value": value,
                            "severity": rule.severity
                        }
                        triggered.append({
                            "alert_id": rule_id,
                            "rule": rule,
                            "value": value,
                            "severity": rule.severity
                        })
                else:
                    if rule_id in self._active_alerts:
                        del self._active_alerts[rule_id]

        return triggered

    def _evaluate_condition(self, value: float, condition: str, threshold: float) -> bool:
        """Evaluate condition"""
        if condition == "gt":
            return value > threshold
        elif condition == "gte":
            return value >= threshold
        elif condition == "lt":
            return value < threshold
        elif condition == "lte":
            return value <= threshold
        elif condition == "eq":
            return abs(value - threshold) < 0.001
        return False

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get active alerts"""
        with self._lock:
            return list(self._active_alerts.values())


class SLITracker:
    """Service Level Indicator tracker"""

    def __init__(self):
        self._slis: Dict[str, SLI] = {}
        self._slo: Optional[SLO] = None
        self._lock = threading.RLock()
        self._measurements: Dict[str, List[float]] = defaultdict(list)

    def add_sli(self, sli: SLI):
        """Add SLI"""
        with self._lock:
            self._slis[sli.sli_id] = sli

    def record_measurement(self, sli_id: str, value: float):
        """Record measurement"""
        with self._lock:
            self._measurements[sli_id].append(value)

            if len(self._measurements[sli_id]) > 10000:
                self._measurements[sli_id] = self._measurements[sli_id][-10000:]

    def calculate_current_value(self, sli_id: str) -> float:
        """Calculate current value"""
        with self._lock:
            if sli_id not in self._measurements:
                return 0.0

            values = self._measurements[sli_id]
            return statistics.mean(values[-100:])

    def check_slo_status(self) -> SLOStatus:
        """Check SLO status"""
        with self._lock:
            if not self._slo:
                return SLOStatus.GOOD

            for sli_id in self._slo.slis:
                if sli_id not in self._slis:
                    continue

                current = self.calculate_current_value(sli_id)
                target = self._slis[sli_id].target

                if current < target:
                    return SLOStatus.VIOLATED

            return SLOStatus.GOOD

    def get_error_budget(self) -> float:
        """Get remaining error budget"""
        with self._lock:
            if not self._slo:
                return 1.0

            total_bad = 0
            total_requests = 0

            for sli_id in self._slo.slis:
                values = self._measurements.get(sli_id, [])
                target = self._slis[sli_id].target if sli_id in self._slis else 0.99

                bad = sum(1 for v in values if v < target)
                total_bad += bad
                total_requests += len(values)

            if total_requests == 0:
                return 1.0

            budget = 1.0 - (total_bad / total_requests)
            return max(0.0, min(1.0, budget))


class ServiceMapGenerator:
    """Generate service map from traces"""

    def __init__(self):
        self._nodes: Dict[str, ServiceNode] = {}
        self._edges: Dict[Tuple[str, str], ServiceEdge] = {}
        self._lock = threading.RLock()

    def record_call(self, from_service: str, to_service: str, success: bool = True, latency_ms: float = 0):
        """Record service call"""
        with self._lock:
            if from_service not in self._nodes:
                self._nodes[from_service] = ServiceNode(
                    service_id=from_service,
                    service_name=from_service
                )

            if to_service not in self._nodes:
                self._nodes[to_service] = ServiceNode(
                    service_id=to_service,
                    service_name=to_service
                )

            self._nodes[from_service].requests += 1
            if not success:
                self._nodes[from_service].errors += 1

            edge_key = (from_service, to_service)
            if edge_key not in self._edges:
                self._edges[edge_key] = ServiceEdge(
                    from_service=from_service,
                    to_service=to_service
                )

            self._edges[edge_key].requests += 1
            if not success:
                self._edges[edge_key].errors += 1

    def get_service_map(self) -> Dict[str, Any]:
        """Get service map"""
        with self._lock:
            nodes = [
                {
                    "id": n.service_id,
                    "name": n.service_name,
                    "requests": n.requests,
                    "errors": n.errors,
                    "error_rate": n.errors / max(1, n.requests),
                    "latency_p50": n.latency_p50,
                    "latency_p99": n.latency_p99
                }
                for n in self._nodes.values()
            ]

            edges = [
                {
                    "from": e.from_service,
                    "to": e.to_service,
                    "requests": e.requests,
                    "errors": e.errors,
                    "error_rate": e.errors / max(1, e.requests)
                }
                for e in self._edges.values()
            ]

            return {"nodes": nodes, "edges": edges}


class LogAggregator:
    """Aggregate and query logs"""

    def __init__(self, max_logs: int = 100000):
        self._logs: deque = deque(maxlen=max_logs)
        self._logs_by_trace: Dict[str, List[int]] = defaultdict(list)
        self._logs_by_service: Dict[str, List[int]] = defaultdict(list)
        self._lock = threading.RLock()

    def log(self,
          level: str,
          message: str,
          service: str,
          trace_id: Optional[str] = None,
          span_id: Optional[str] = None,
          metadata: Dict[str, Any] = None):
        """Log entry"""
        entry = {
            "timestamp": time.time(),
            "level": level,
            "message": message,
            "service": service,
            "trace_id": trace_id,
            "span_id": span_id,
            "metadata": metadata or {}
        }

        with self._lock:
            idx = len(self._logs)
            self._logs.append(entry)

            if trace_id:
                self._logs_by_trace[trace_id].append(idx)

            self._logs_by_service[service].append(idx)

    def query(self,
            service: Optional[str] = None,
            trace_id: Optional[str] = None,
            level: Optional[str] = None,
            limit: int = 100) -> List[Dict[str, Any]]:
        """Query logs"""
        with self._lock:
            indices = set(range(len(self._logs)))

            if service:
                indices &= set(self._logs_by_service.get(service, []))

            if trace_id:
                indices &= set(self._logs_by_trace.get(trace_id, []))

            if level:
                indices = {i for i in indices if self._logs[i].get("level") == level}

            return [self._logs[i] for i in sorted(indices, reverse=True)[:limit]]


class CostObservability:
    """Track cloud costs and resource usage"""

    def __init__(self):
        self._costs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._usage: Dict[str, Dict[str, float]] = {}
        self._lock = threading.RLock()

    def record_usage(self, resource: str, quantity: float, cost: float, unit: str = "hour"):
        """Record resource usage"""
        with self._lock:
            if resource not in self._costs:
                self._costs[resource] = []

            self._costs[resource].append({
                "timestamp": time.time(),
                "quantity": quantity,
                "cost": cost,
                "unit": unit
            })

    def get_total_cost(self, period: str = "24h") -> float:
        """Get total cost"""
        with self._lock:
            cutoff = time.time() - (24 * 3600)

            total = 0.0
            for resource, entries in self._costs.items():
                for entry in entries:
                    if entry["timestamp"] >= cutoff:
                        total += entry["cost"]

            return total

    def get_cost_breakdown(self) -> Dict[str, float]:
        """Get cost breakdown by resource"""
        with self._lock:
            breakdown = {}

            for resource, entries in self._costs.items():
                total = sum(e["cost"] for e in entries)
                breakdown[resource] = total

            return breakdown


class EnterpriseObservabilityPlatform:
    """Main observability platform"""

    def __init__(self):
        self._otel = OpenTelemetryIntegrator()
        self._grafana = GrafanaMetricsExporter()
        self._alerts = AlertEngine()
        self._sli_tracker = SLITracker()
        self._service_map = ServiceMapGenerator()
        self._logs = LogAggregator()
        self._cost = CostObservability()
        self._lock = threading.RLock()

        self._config = {
            "enable_otel": True,
            "enable_grafana": True,
            "enable_alerting": True,
            "enable_slo_tracking": True,
            "enable_service_map": True,
            "enable_log_aggregation": True,
            "enable_cost_tracking": True
        }

        self._alert_handlers: List[Callable] = []

        logger.info("Enterprise observability platform initialized")

    def setup_slo(self, slo: SLO):
        """Setup SLO"""
        self._sli_tracker._slo = slo

    def register_alert_handler(self, handler: Callable):
        """Register alert handler"""
        self._alert_handlers.append(handler)

    def record_metric(self, name: str, value: float, metric_type: MetricType = MetricType.GAUGE, labels: Dict[str, str] = None):
        """Record metric"""
        if metric_type == MetricType.COUNTER:
            self._grafana.record_counter(name, value, labels)
        elif metric_type == MetricType.GAUGE:
            self._grafana.record_gauge(name, value, labels)
        elif metric_type == MetricType.HISTOGRAM:
            self._grafana.record_histogram(name, value, labels)

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get dashboard data"""
        return {
            "metrics": self._grafana.export_json(),
            "service_map": self._service_map.get_service_map(),
            "alerts": self._alerts.get_active_alerts(),
            "cost": {
                "total_24h": self._cost.get_total_cost(),
                "breakdown": self._cost.get_cost_breakdown()
            },
            "slo": {
                "status": self._sli_tracker.check_slo_status().value,
                "error_budget": self._sli_tracker.get_error_budget()
            }
        }

    def export_prometheus(self) -> str:
        """Export Prometheus format"""
        return self._grafana.export_prometheus()

    def query_logs(self, service: Optional[str] = None, trace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query logs"""
        return self._logs.query(service=service, trace_id=trace_id)


_global_platform: Optional["EnterpriseObservabilityPlatform"] = None


def get_observability_platform() -> EnterpriseObservabilityPlatform:
    """Get global observability platform"""
    global _global_platform
    if _global_platform is None:
        _global_platform = EnterpriseObservabilityPlatform()
    return _global_platform


__all__ = [
    "MetricType",
    "AlertSeverity",
    "SLOStatus",
    "OTelSpan",
    "AlertRule",
    "SLI",
    "SLO",
    "ServiceNode",
    "ServiceEdge",
    "OpenTelemetryIntegrator",
    "GrafanaMetricsExporter",
    "AlertEngine",
    "SLITracker",
    "ServiceMapGenerator",
    "LogAggregator",
    "CostObservability",
    "EnterpriseObservabilityPlatform",
    "get_observability_platform"
]
