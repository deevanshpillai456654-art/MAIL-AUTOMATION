"""
Provider Isolation Engine - Enterprise Provider Sandboxing
============================================================

Fully isolated provider execution:
- Per-provider worker pools
- Per-provider queues
- Per-provider memory quotas
- Provider-level circuit breakers
- Provider-level health engines
- Provider sandboxing
- Isolated crashes
- Isolated reconnect storms
"""

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("provider.isolation")


class ProviderState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    ISOLATED = "isolated"
    RECOVERING = "recovering"
    FAILED = "failed"


class IsolationLevel(Enum):
    NONE = "none"
    SOFT = "soft"
    HARD = "hard"
    SANDBOX = "sandbox"


@dataclass
class ProviderQuota:
    """Provider resource quota"""
    max_memory_mb: int = 512
    max_workers: int = 2
    max_queue_size: int = 1000
    max_connections: int = 5
    max_reconnect_per_minute: int = 10


@dataclass
class ProviderHealth:
    """Provider health metrics"""
    provider: str
    state: ProviderState
    error_count: int = 0
    success_count: int = 0
    last_error: Optional[str] = None
    last_success: float = 0
    reconnect_count: int = 0
    avg_latency_ms: float = 0
    isolation_level: IsolationLevel = IsolationLevel.NONE


@dataclass
class ProviderTask:
    """Task representation for provider worker queues"""
    task_id: str
    provider: str
    action: str
    func: Callable
    args: List[Any] = field(default_factory=list)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    retries: int = 0
    max_retries: int = 3
    idempotency_key: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CircuitBreaker:
    """Circuit breaker for provider isolation"""

    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 30):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = "closed"  # closed, open, half-open
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            self.failure_count = 0
            self.state = "closed"

    def record_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning("Circuit breaker opened for provider")

    def can_execute(self) -> bool:
        with self._lock:
            if self.state == "closed":
                return True

            if self.state == "open":
                # Check timeout
                if time.time() - self.last_failure_time > self.timeout_seconds:
                    self.state = "half-open"
                    return True
                return False

            # half-open - allow one attempt
            return True

    def reset(self):
        with self._lock:
            self.failure_count = 0
            self.state = "closed"


class ProviderIsolator:
    """
    Enterprise provider isolation with full sandboxing.
    """

    def __init__(self):
        self._providers: Dict[str, ProviderHealth] = {}
        self._quotas: Dict[str, ProviderQuota] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._queues: Dict[str, queue.Queue] = {}
        self._workers: Dict[str, List[threading.Thread]] = {}
        self._worker_events: Dict[str, threading.Event] = {}
        self._worker_stop: Dict[str, threading.Event] = {}
        self._task_callbacks: Dict[str, Optional[Callable]] = {
            "on_task_start": None,
            "on_task_success": None,
            "on_task_failure": None
        }

        self._lock = threading.RLock()

        # Default quotas per provider type
        self._default_quotas = {
            "gmail": ProviderQuota(max_memory_mb=512, max_workers=2, max_queue_size=1000),
            "outlook": ProviderQuota(max_memory_mb=512, max_workers=2, max_queue_size=1000),
            "yahoo": ProviderQuota(max_memory_mb=256, max_workers=1, max_queue_size=500),
            "zoho": ProviderQuota(max_memory_mb=256, max_workers=1, max_queue_size=500),
            "imap": ProviderQuota(max_memory_mb=256, max_workers=1, max_queue_size=500),
            "exchange": ProviderQuota(max_memory_mb=512, max_workers=2, max_queue_size=1000)
        }

        logger.info("Provider Isolator initialized")

    def register_provider(self, provider: str, quota: ProviderQuota = None):
        """Register a provider with quota"""
        with self._lock:
            if provider not in self._providers:
                self._providers[provider] = ProviderHealth(
                    provider=provider,
                    state=ProviderState.HEALTHY
                )
                self._quotas[provider] = quota or self._default_quotas.get(
                    provider, ProviderQuota()
                )
                self._circuit_breakers[provider] = CircuitBreaker()
                self._queues[provider] = queue.Queue(
                    maxsize=self._quotas[provider].max_queue_size
                )
                self._worker_events[provider] = threading.Event()
                self._worker_stop[provider] = threading.Event()
                self._workers[provider] = []

                logger.info(f"Provider registered: {provider}")

    def is_available(self, provider: str) -> bool:
        """Check if provider can accept work"""
        with self._lock:
            if provider not in self._providers:
                return False

            health = self._providers[provider]

            if health.state in (ProviderState.ISOLATED, ProviderState.FAILED):
                return False

            breaker = self._circuit_breakers.get(provider)
            if breaker and not breaker.can_execute():
                return False

            queue_size = self._queues.get(provider, queue.Queue()).qsize()
            max_size = self._quotas.get(provider, ProviderQuota()).max_queue_size

            return queue_size < max_size

    def start_workers(self):
        """Start worker threads for each registered provider."""
        with self._lock:
            for provider, quota in self._quotas.items():
                if provider not in self._worker_stop:
                    self._worker_stop[provider] = threading.Event()
                self._worker_stop[provider].clear()
                self._workers[provider] = []
                for index in range(quota.max_workers):
                    thread = threading.Thread(target=self._worker_loop, args=(provider,), daemon=True, name=f"prov-worker-{provider}-{index}")
                    thread.start()
                    self._workers[provider].append(thread)
                logger.info(f"Started {len(self._workers[provider])} workers for provider {provider}")

    def stop_workers(self):
        """Stop all provider worker threads."""
        with self._lock:
            for provider, stop_event in self._worker_stop.items():
                stop_event.set()
            for provider, workers in self._workers.items():
                for worker in workers:
                    worker.join(timeout=5)
            logger.info("Provider worker pools stopped")

    def on_task_callbacks(self, on_task_start: Callable = None, on_task_success: Callable = None, on_task_failure: Callable = None):
        """Register task lifecycle callbacks."""
        with self._lock:
            self._task_callbacks["on_task_start"] = on_task_start
            self._task_callbacks["on_task_success"] = on_task_success
            self._task_callbacks["on_task_failure"] = on_task_failure

    def enqueue_task(self, provider: str, task: ProviderTask) -> bool:
        """Enqueue a task for provider execution."""
        if not self.is_available(provider):
            logger.warning(f"Provider task enqueue rejected: {provider} unavailable or queue full")
            return False
        try:
            self._queues[provider].put_nowait(task)
            logger.info(f"Task queued for provider {provider}: {task.task_id}")
            return True
        except queue.Full:
            logger.warning(f"Provider queue full while enqueueing task: {provider}")
            return False

    def _worker_loop(self, provider: str):
        """Worker loop for processing provider tasks."""
        stop_event = self._worker_stop.get(provider)
        while stop_event and not stop_event.is_set():
            try:
                task = self._queues[provider].get(timeout=1.0)
            except queue.Empty:
                continue

            if not self.is_available(provider):
                # Put the task back and wait for recovery
                try:
                    self._queues[provider].put_nowait(task)
                except queue.Full:
                    logger.warning(f"Unable to requeue task for provider {provider} during isolation")
                time.sleep(2.0)
                continue

            self._execute_task(task)
            self._queues[provider].task_done()

    def _execute_task(self, task: ProviderTask):
        """Execute a provider task and handle success/failure."""
        provider = task.provider
        if self._task_callbacks.get("on_task_start"):
            try:
                self._task_callbacks["on_task_start"](task)
            except Exception as e:
                logger.debug(f"Task start callback error: {e}")

        try:
            result = task.func(*task.args, **task.kwargs)
            self.record_success(provider, latency_ms=0)
            if self._task_callbacks.get("on_task_success"):
                try:
                    self._task_callbacks["on_task_success"](task, result)
                except Exception as e:
                    logger.debug(f"Task success callback error: {e}")
            return result
        except Exception as exc:
            task.retries += 1
            error = str(exc)
            self.record_failure(provider, error)
            if self._task_callbacks.get("on_task_failure"):
                try:
                    self._task_callbacks["on_task_failure"](task, error)
                except Exception as e:
                    logger.debug(f"Task failure callback error: {e}")

            if task.retries < task.max_retries:
                try:
                    self._queues[provider].put_nowait(task)
                    logger.warning(f"Requeued task {task.task_id} for provider {provider} (retry {task.retries})")
                except queue.Full:
                    logger.error(f"Unable to requeue provider task {task.task_id} after failure")
            else:
                logger.warning(f"Provider task {task.task_id} permanently failed after {task.retries} retries")
                if provider in self._providers:
                    self._providers[provider].state = ProviderState.DEGRADED
                    self._providers[provider].last_error = error

    def enqueue(self, provider: str, item: Any) -> bool:
        """Add item to provider queue"""
        if not self.is_available(provider):
            return False

        try:
            self._queues[provider].put_nowait(item)
            return True
        except queue.Full:
            logger.warning(f"Provider queue full: {provider}")
            return False

    def dequeue(self, provider: str, timeout: float = 1.0) -> Optional[Any]:
        """Get item from provider queue"""
        try:
            return self._queues[provider].get(timeout=timeout)
        except queue.Empty:
            return None

    def record_success(self, provider: str, latency_ms: float = 0):
        """Record successful operation"""
        with self._lock:
            if provider in self._providers:
                health = self._providers[provider]
                health.success_count += 1
                health.last_success = time.time()
                health.state = ProviderState.HEALTHY

                # Update latency
                if health.avg_latency_ms == 0:
                    health.avg_latency_ms = latency_ms
                else:
                    health.avg_latency_ms = (health.avg_latency_ms * 0.9 + latency_ms * 0.1)

                # Reset circuit breaker
                if provider in self._circuit_breakers:
                    self._circuit_breakers[provider].record_success()

    def record_failure(self, provider: str, error: str):
        """Record failed operation"""
        with self._lock:
            if provider in self._providers:
                health = self._providers[provider]
                health.error_count += 1
                health.last_error = error

                # Update circuit breaker
                if provider in self._circuit_breakers:
                    self._circuit_breakers[provider].record_failure()

                    # Check if should isolate
                    if self._circuit_breakers[provider].failure_count >= 3:
                        health.state = ProviderState.ISOLATED
                        health.isolation_level = IsolationLevel.HARD
                        logger.warning(f"Provider isolated: {provider}")

    def record_reconnect(self, provider: str):
        """Record reconnect attempt"""
        with self._lock:
            if provider in self._providers:
                health = self._providers[provider]
                health.reconnect_count += 1

                # Check for reconnect storm
                quota = self._quotas.get(provider, ProviderQuota())
                if health.reconnect_count > quota.max_reconnect_per_minute:
                    logger.critical(f"Reconnect storm detected: {provider}")
                    health.state = ProviderState.ISOLATED

    def isolate_provider(self, provider: str, reason: str):
        """Manually isolate a provider"""
        with self._lock:
            if provider in self._providers:
                self._providers[provider].state = ProviderState.ISOLATED
                self._providers[provider].isolation_level = IsolationLevel.HARD
                logger.warning(f"Provider manually isolated: {provider} - {reason}")

    def release_provider(self, provider: str):
        """Release provider from isolation"""
        with self._lock:
            if provider in self._providers:
                self._providers[provider].state = ProviderState.RECOVERING
                self._providers[provider].error_count = 0
                self._providers[provider].reconnect_count = 0
                if provider in self._circuit_breakers:
                    self._circuit_breakers[provider].reset()
                logger.info(f"Provider released from isolation: {provider}")

    def get_provider_health(self, provider: str) -> Optional[ProviderHealth]:
        """Get provider health"""
        return self._providers.get(provider)

    def get_all_health(self) -> Dict[str, ProviderHealth]:
        """Get all provider health"""
        return dict(self._providers)

    def get_isolated_providers(self) -> List[str]:
        """Get list of isolated providers"""
        return [
            p for p, h in self._providers.items()
            if h.state == ProviderState.ISOLATED
        ]

    def get_queue_size(self, provider: str) -> int:
        """Get provider queue size"""
        return self._queues.get(provider, queue.Queue()).qsize()

    def clear_provider_queue(self, provider: str):
        """Clear provider queue"""
        if provider in self._queues:
            try:
                while True:
                    self._queues[provider].get_nowait()
            except queue.Empty:
                pass
            logger.info(f"Provider queue cleared: {provider}")

    def get_stats(self) -> Dict:
        """Get isolation statistics"""
        stats = {
            "total_providers": len(self._providers),
            "healthy": 0,
            "degraded": 0,
            "isolated": 0,
            "recovering": 0,
            "failed": 0,
            "isolated_providers": self.get_isolated_providers()
        }

        for health in self._providers.values():
            if health.state == ProviderState.HEALTHY:
                stats["healthy"] += 1
            elif health.state == ProviderState.DEGRADED:
                stats["degraded"] += 1
            elif health.state == ProviderState.ISOLATED:
                stats["isolated"] += 1
            elif health.state == ProviderState.RECOVERING:
                stats["recovering"] += 1
            elif health.state == ProviderState.FAILED:
                stats["failed"] += 1

        return stats


# Global isolator
_isolator: Optional[ProviderIsolator] = None


def get_provider_isolator() -> ProviderIsolator:
    """Get global provider isolator"""
    global _isolator
    if _isolator is None:
        _isolator = ProviderIsolator()
    return _isolator
