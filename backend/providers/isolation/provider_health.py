"""
Provider Health Engine - Per-Provider Health Tracking and Auto-Degradation
======================================================================

Enterprise health monitoring:
- Per-provider health tracking: state, error_count, success_count, latency_avg, last_error
- Health metrics: error_rate, success_rate, avg_latency
- Auto-degradation: if error_rate > 20%, reduce polling frequency
- Provider heartbeat monitoring (ping every 60s)
- Reconnect storm protection (max 3 reconnects per minute)
"""

import time
import threading
import logging
import statistics
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List, Callable
from enum import Enum
from collections import deque

logger = logging.getLogger("provider.health")

PROVIDERS = ["gmail", "outlook", "yahoo", "zoho", "proton", "imap"]


class HealthState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


@dataclass
class HealthMetrics:
    error_rate: float = 0.0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    total_operations: int = 0
    total_successes: int = 0
    total_failures: int = 0


@dataclass
class ProviderHealthData:
    provider: str
    state: HealthState = HealthState.UNKNOWN
    error_count: int = 0
    success_count: int = 0
    latency_avg_ms: float = 0.0
    last_error: Optional[str] = None
    last_success: float = 0
    last_ping: float = 0
    reconnect_count: int = 0
    reconnect_timestamps: List[float] = field(default_factory=list)
    recent_errors: List[str] = field(default_factory=list)
    recent_latencies: deque = field(default_factory=lambda: deque(maxlen=100))
    polling_interval_seconds: int = 300
    is_responding: bool = True


class ProviderHealthEngine:
    """
    Per-provider health tracking with auto-degradation.
    Monitors health metrics, detects issues, and auto-adjusts polling.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._health_data: Dict[str, ProviderHealthData] = {}
        self._health_callbacks: Dict[str, List[Callable]] = {}
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()
        self._global_lock = threading.RLock()

        for provider in PROVIDERS:
            self._health_data[provider] = ProviderHealthData(provider=provider)

        self._initialized = True
        logger.info("ProviderHealthEngine initialized for %d providers", len(PROVIDERS))

    def start_monitoring(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True, name="health-monitor")
        self._monitor_thread.start()
        logger.info("Health monitoring started")

    def stop_monitoring(self):
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=10)
        logger.info("Health monitoring stopped")

    def _monitor_loop(self):
        while not self._stop_monitor.is_set():
            try:
                self._check_heartbeats()
                self._enforce_reconnect_limits()
                self._apply_auto_degradation()
            except Exception as e:
                logger.error("Health monitor error: %s", e)
            time.sleep(30)

    def _check_heartbeats(self):
        with self._global_lock:
            current_time = time.time()
            for provider, data in self._health_data.items():
                if data.last_ping > 0 and (current_time - data.last_ping) > 120:
                    if data.is_responding:
                        data.is_responding = False
                        data.state = HealthState.FAILED
                        logger.warning("Provider %s heartbeat timeout", provider)
                        self._notify_callbacks(provider, "heartbeat_timeout")

                if data.last_success > 0 and (current_time - data.last_success) > 300:
                    if data.state == HealthState.HEALTHY:
                        data.state = HealthState.DEGRADED

    def _enforce_reconnect_limits(self):
        with self._global_lock:
            current_time = time.time()
            for provider, data in self._health_data.items():
                self._cleanup_old_reconnects(provider)

                recent_count = len(data.reconnect_timestamps)
                if recent_count >= 3:
                    data.state = HealthState.FAILED
                    logger.critical("Reconnect storm detected for %s: %d reconnects", provider, recent_count)
                    self._notify_callbacks(provider, "reconnect_storm")

    def _apply_auto_degradation(self):
        with self._global_lock:
            for provider, data in self._health_data.items():
                metrics = self.get_metrics(provider)

                if metrics.error_rate > 0.20:
                    old_interval = data.polling_interval_seconds
                    data.polling_interval_seconds = min(900, int(old_interval * 1.5))
                    data.state = HealthState.DEGRADED
                    if old_interval != data.polling_interval_seconds:
                        logger.info("Provider %s degraded: polling interval %d -> %d",
                                   provider, old_interval, data.polling_interval_seconds)
                        self._notify_callbacks(provider, "auto_degraded")

                elif metrics.error_rate < 0.10 and data.state == HealthState.DEGRADED:
                    data.polling_interval_seconds = max(300, int(data.polling_interval_seconds * 0.67))
                    logger.info("Provider %s recovery: polling interval restored to %d",
                                provider, data.polling_interval_seconds)

    def _cleanup_old_reconnects(self, provider: str):
        data = self._health_data[provider]
        current_time = time.time()
        data.reconnect_timestamps = [
            ts for ts in data.reconnect_timestamps
            if current_time - ts < 60
        ]

    def record_success(self, provider: str, latency_ms: float = 0):
        with self._global_lock:
            if provider not in self._health_data:
                return

            data = self._health_data[provider]
            data.success_count += 1
            data.last_success = time.time()
            data.last_ping = time.time()
            data.is_responding = True

            data.recent_latencies.append(latency_ms)
            if data.recent_latencies:
                data.latency_avg_ms = statistics.mean(data.recent_latencies)

            if data.state in (HealthState.DEGRADED, HealthState.RECOVERING):
                metrics = self.get_metrics(provider)
                if metrics.error_rate < 0.10:
                    data.state = HealthState.HEALTHY

            self._notify_callbacks(provider, "success")

    def record_failure(self, provider: str, error: str):
        with self._global_lock:
            if provider not in self._health_data:
                return

            data = self._health_data[provider]
            data.error_count += 1
            data.last_error = error
            data.last_ping = time.time()
            data.recent_errors.append(error)

            if len(data.recent_errors) > 10:
                data.recent_errors = data.recent_errors[-10:]

            metrics = self.get_metrics(provider)
            if metrics.error_rate > 0.50:
                data.state = HealthState.FAILED
                logger.error("Provider %s marked as failed: error rate %.1f%%",
                             provider, metrics.error_rate * 100)
            elif metrics.error_rate > 0.20:
                data.state = HealthState.DEGRADED

            self._notify_callbacks(provider, "failure")

    def record_reconnect(self, provider: str):
        with self._global_lock:
            if provider not in self._health_data:
                return

            data = self._health_data[provider]
            data.reconnect_count += 1
            data.reconnect_timestamps.append(time.time())
            self._cleanup_old_reconnects(provider)

    def ping_provider(self, provider: str, check_func: Callable = None) -> bool:
        with self._global_lock:
            if provider not in self._health_data:
                return False

            data = self._health_data[provider]
            data.last_ping = time.time()

            if check_func:
                try:
                    check_func()
                    data.is_responding = True
                    return True
                except Exception as e:
                    data.is_responding = False
                    data.last_error = str(e)
                    return False

            return data.is_responding

    def get_metrics(self, provider: str) -> HealthMetrics:
        with self._global_lock:
            if provider not in self._health_data:
                return HealthMetrics()

            data = self._health_data[provider]
            total = data.success_count + data.error_count

            if total == 0:
                return HealthMetrics()

            return HealthMetrics(
                error_rate=data.error_count / total,
                success_rate=data.success_count / total,
                avg_latency_ms=data.latency_avg_ms,
                total_operations=total,
                total_successes=data.success_count,
                total_failures=data.error_count,
            )

    def get_health(self, provider: str) -> ProviderHealthData:
        return self._health_data.get(provider)

    def get_all_health(self) -> Dict[str, ProviderHealthData]:
        return dict(self._health_data)

    def get_state(self, provider: str) -> HealthState:
        return self._health_data.get(provider, ProviderHealthData(provider=provider)).state

    def get_polling_interval(self, provider: str) -> int:
        return self._health_data.get(provider, ProviderHealthData(provider=provider)).polling_interval_seconds

    def register_callback(self, provider: str, callback: Callable):
        with self._global_lock:
            if provider not in self._health_callbacks:
                self._health_callbacks[provider] = []
            self._health_callbacks[provider].append(callback)

    def _notify_callbacks(self, provider: str, event: str):
        callbacks = self._health_callbacks.get(provider, [])
        for callback in callbacks:
            try:
                callback(provider, event, self._health_data[provider])
            except Exception as e:
                logger.error("Health callback error for %s: %s", provider, e)

    def get_failed_providers(self) -> List[str]:
        return [
            provider for provider, data in self._health_data.items()
            if data.state == HealthState.FAILED
        ]

    def get_degraded_providers(self) -> List[str]:
        return [
            provider for provider, data in self._health_data.items()
            if data.state == HealthState.DEGRADED
        ]

    def get_summary(self) -> Dict[str, Any]:
        with self._global_lock:
            return {
                "total": len(self._health_data),
                "healthy": sum(1 for d in self._health_data.values() if d.state == HealthState.HEALTHY),
                "degraded": sum(1 for d in self._health_data.values() if d.state == HealthState.DEGRADED),
                "failed": sum(1 for d in self._health_data.values() if d.state == HealthState.FAILED),
                "recovering": sum(1 for d in self._health_data.values() if d.state == HealthState.RECOVERING),
                "providers": {p: d.state.value for p, d in self._health_data.items()},
            }


def get_health_engine() -> ProviderHealthEngine:
    return ProviderHealthEngine()
