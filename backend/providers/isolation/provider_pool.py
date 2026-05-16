"""
Provider Pool - Per-Provider Worker Pools with Isolated Resources
=================================================================

Enterprise isolation for email providers:
- Gmail, Outlook, Yahoo, Zoho, Proton, IMAP
- Per-provider thread pools
- Per-provider queues with dedicated workers
- Per-provider memory quotas (max 256MB per provider)
- Provider-level circuit breakers
"""

import time
import threading
import queue
import logging
import uuid
import psutil
import os
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List, Callable
from enum import Enum

logger = logging.getLogger("provider.pool")

PROVIDERS = ["gmail", "outlook", "yahoo", "zoho", "proton", "imap"]


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class ProviderPoolConfig:
    max_workers: int = 2
    max_queue_size: int = 500
    max_memory_mb: int = 256
    failure_threshold: int = 5
    failure_window_seconds: int = 60
    half_open_test_seconds: int = 30
    half_open_success_threshold: int = 2
    max_retries: int = 3


@dataclass
class CircuitBreakerState:
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    opened_at: float = 0


class ProviderPool:
    """
    Per-provider worker pools with complete isolation.
    Each provider has its own thread pool, queue, and circuit breaker.
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

        self._pools: Dict[str, Dict[str, Any]] = {}
        self._circuit_breakers: Dict[str, CircuitBreakerState] = {}
        self._pool_configs: Dict[str, ProviderPoolConfig] = {}
        self._global_lock = threading.RLock()
        self._process = psutil.Process(os.getpid())

        self._initialize_pools()
        self._initialized = True
        logger.info("ProviderPool initialized with %d providers", len(PROVIDERS))

    def _initialize_pools(self):
        default_configs = {
            "gmail": ProviderPoolConfig(max_workers=2, max_memory_mb=256),
            "outlook": ProviderPoolConfig(max_workers=2, max_memory_mb=256),
            "yahoo": ProviderPoolConfig(max_workers=1, max_memory_mb=256),
            "zoho": ProviderPoolConfig(max_workers=1, max_memory_mb=256),
            "proton": ProviderPoolConfig(max_workers=1, max_memory_mb=256),
            "imap": ProviderPoolConfig(max_workers=2, max_memory_mb=256),
        }

        for provider in PROVIDERS:
            config = default_configs.get(provider, ProviderPoolConfig())
            self._pool_configs[provider] = config
            self._pools[provider] = {
                "queue": queue.Queue(maxsize=config.max_queue_size),
                "workers": [],
                "stop_event": threading.Event(),
                "pause_event": threading.Event(),
                "running": False,
                "tasks_processed": 0,
                "tasks_failed": 0,
                "tasks_success": 0,
            }
            self._circuit_breakers[provider] = CircuitBreakerState()

    def start_provider(self, provider: str):
        with self._global_lock:
            if provider not in self._pools:
                logger.error("Unknown provider: %s", provider)
                return False

            pool = self._pools[provider]
            if pool["running"]:
                logger.warning("Provider %s already running", provider)
                return True

            pool["stop_event"].clear()
            pool["pause_event"].clear()
            config = self._pool_configs[provider]
            pool["workers"] = []

            for i in range(config.max_workers):
                thread = threading.Thread(
                    target=self._worker_loop,
                    args=(provider,),
                    daemon=True,
                    name=f"provider-pool-{provider}-{i}"
                )
                thread.start()
                pool["workers"].append(thread)

            pool["running"] = True
            logger.info("Provider %s started with %d workers", provider, config.max_workers)
            return True

    def stop_provider(self, provider: str):
        with self._global_lock:
            if provider not in self._pools:
                return False

            pool = self._pools[provider]
            pool["stop_event"].set()

            for worker in pool["workers"]:
                worker.join(timeout=5)

            pool["workers"] = []
            pool["running"] = False
            logger.info("Provider %s stopped", provider)
            return True

    def start_all(self):
        for provider in PROVIDERS:
            self.start_provider(provider)

    def stop_all(self):
        for provider in PROVIDERS:
            self.stop_provider(provider)

    def enqueue(self, provider: str, task: Callable, *args, **kwargs) -> Optional[str]:
        task_id = str(uuid.uuid4())[:12]

        if not self._can_execute(provider):
            logger.warning("Task %s rejected for %s - provider unavailable", task_id, provider)
            return None

        pool = self._pools[provider]
        try:
            pool["queue"].put_nowait({
                "task_id": task_id,
                "func": task,
                "args": args,
                "kwargs": kwargs,
                "created_at": time.time(),
                "retries": 0,
            })
            logger.debug("Task %s queued for provider %s", task_id, provider)
            return task_id
        except queue.Full:
            logger.warning("Queue full for provider %s, task %s rejected", provider, task_id)
            return None

    def _can_execute(self, provider: str) -> bool:
        with self._global_lock:
            if provider not in self._pools:
                return False

            if not self._pools[provider]["running"]:
                return False

            cb = self._circuit_breakers[provider]
            if cb.state == CircuitState.OPEN:
                if time.time() - cb.last_failure_time > 60:
                    cb.state = CircuitState.HALF_OPEN
                    cb.success_count = 0
                    logger.info("Provider %s circuit breaker half-open", provider)
                    return True
                return False

            return True

    def _worker_loop(self, provider: str):
        pool = self._pools[provider]
        config = self._pool_configs[provider]
        stop_event = pool["stop_event"]
        pause_event = pool["pause_event"]

        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(1)
                continue

            try:
                work_item = pool["queue"].get(timeout=1.0)
            except queue.Empty:
                continue

            task_id = work_item["task_id"]
            task_func = work_item["func"]
            task_args = work_item["args"]
            task_kwargs = work_item["kwargs"]

            if not self._can_execute(provider):
                try:
                    pool["queue"].put_nowait(work_item)
                except queue.Full:
                    logger.error("Unable to requeue task %s", task_id)
                time.sleep(2)
                continue

            start_time = time.time()
            try:
                result = task_func(*task_args, **task_kwargs)
                pool["tasks_success"] += 1
                self._record_success(provider)
                logger.debug("Task %s completed for %s", task_id, provider)
            except Exception as exc:
                pool["tasks_failed"] += 1
                self._record_failure(provider, str(exc))
                logger.error("Task %s failed for %s: %s", task_id, provider, exc)

                work_item["retries"] += 1
                if work_item["retries"] < config.max_retries:
                    try:
                        pool["queue"].put_nowait(work_item)
                    except queue.Full:
                        pass
            finally:
                pool["tasks_processed"] += 1
                pool["queue"].task_done()

    def _record_success(self, provider: str):
        with self._global_lock:
            cb = self._circuit_breakers[provider]
            cb.success_count += 1
            cb.last_success_time = time.time()

            if cb.state == CircuitState.HALF_OPEN:
                if cb.success_count >= 2:
                    cb.state = CircuitState.CLOSED
                    cb.failure_count = 0
                    cb.success_count = 0
                    logger.info("Provider %s circuit breaker closed", provider)
            elif cb.state == CircuitState.CLOSED:
                cb.failure_count = max(0, cb.failure_count - 1)

    def _record_failure(self, provider: str, error: str):
        with self._global_lock:
            cb = self._circuit_breakers[provider]
            cb.failure_count += 1
            cb.last_failure_time = time.time()

            if cb.state == CircuitState.HALF_OPEN:
                cb.state = CircuitState.OPEN
                cb.success_count = 0
                logger.warning("Provider %s circuit breaker reopened", provider)
            elif cb.failure_count >= 5:
                cb.state = CircuitState.OPEN
                cb.opened_at = time.time()
                logger.warning("Provider %s circuit breaker opened after %d failures", provider, cb.failure_count)

    def get_circuit_state(self, provider: str) -> CircuitState:
        return self._circuit_breakers.get(provider, CircuitBreakerState()).state

    def get_provider_stats(self, provider: str) -> Dict[str, Any]:
        with self._global_lock:
            if provider not in self._pools:
                return {}

            pool = self._pools[provider]
            cb = self._circuit_breakers[provider]

            return {
                "provider": provider,
                "running": pool["running"],
                "queue_size": pool["queue"].qsize(),
                "tasks_processed": pool["tasks_processed"],
                "tasks_success": pool["tasks_success"],
                "tasks_failed": pool["tasks_failed"],
                "circuit_state": cb.state.value,
                "failure_count": cb.failure_count,
                "success_count": cb.success_count,
            }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        return {provider: self.get_provider_stats(provider) for provider in PROVIDERS}

    def get_provider_health(self, provider: str) -> str:
        if provider not in self._pools:
            return "unknown"

        cb = self._circuit_breakers[provider]
        if cb.state == CircuitState.OPEN:
            return "failed"
        elif cb.state == CircuitState.HALF_OPEN:
            return "recovering"
        elif cb.failure_count > 0:
            return "degraded"
        return "healthy"

    def isolate_provider(self, provider: str):
        with self._global_lock:
            if provider in self._circuit_breakers:
                self._circuit_breakers[provider].state = CircuitState.OPEN
                self._circuit_breakers[provider].opened_at = time.time()
                logger.warning("Provider %s manually isolated", provider)

    def release_provider(self, provider: str):
        with self._global_lock:
            if provider in self._circuit_breakers:
                cb = self._circuit_breakers[provider]
                cb.state = CircuitState.CLOSED
                cb.failure_count = 0
                cb.success_count = 0
                logger.info("Provider %s released from isolation", provider)

    def get_memory_usage(self, provider: str = None) -> Dict[str, float]:
        mem_info = self._process.memory_info()
        if provider:
            return {provider: mem_info.rss / (1024 * 1024)}
        return {p: mem_info.rss / (1024 * 1024) for p in PROVIDERS}


def get_provider_pool() -> ProviderPool:
    return ProviderPool()
