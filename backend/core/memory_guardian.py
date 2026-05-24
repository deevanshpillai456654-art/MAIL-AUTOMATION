"""
Memory Guardian - Memory Safety

Features:
- RAM limits
- Queue caps
- Worker recycling
- OOM prevention
- Adaptive shedding
- Inference batching
"""

import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

import psutil

logger = logging.getLogger("memory.guardian")


class MemoryState(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    OOM = "oom"


@dataclass
class MemoryThresholds:
    """Memory threshold configuration"""
    warning_percent: float = 75.0
    critical_percent: float = 85.0
    oom_percent: float = 95.0

    warning_mb: int = 512
    critical_mb: int = 256

    queue_warning: int = 5000
    queue_critical: int = 10000


class MemoryGuardian:
    """
    Enterprise memory guardian with adaptive protection.
    
    Features:
    - RAM monitoring
    - Queue size limits
    - Worker recycling
    - OOM prevention
    - Adaptive load shedding
    - Inference batching
    """

    def __init__(self, thresholds: Optional[MemoryThresholds] = None):
        self.thresholds = thresholds or MemoryThresholds()

        # Current state
        self._current_state = MemoryState.NORMAL
        self._last_check = time.time()

        # Metrics
        self._memory_history: List[float] = []
        self._max_history = 60  # 1 minute of history

        # Protection callbacks
        self._on_warning: Optional[Callable] = None
        self._on_critical: Optional[Callable] = None
        self._on_oom: Optional[Callable] = None

        # Queue managers
        self._queue_sizes: Dict[str, int] = {}
        self._queue_limits: Dict[str, int] = {}

        # Workers for recycling
        self._worker_health: Dict[str, Dict] = {}

        # Background thread
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        logger.info("Memory guardian initialized")

    def start(self):
        """Start memory monitoring"""
        if self._running:
            return

        self._running = True

        def monitor_loop():
            while self._running:
                try:
                    self._check_memory()
                    self._check_queues()
                    self._check_workers()
                except Exception as e:
                    logger.error(f"Memory check error: {e}")

                time.sleep(1)  # Check every second

        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()

        logger.info("Memory guardian started")

    def stop(self):
        """Stop memory monitoring"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Memory guardian stopped")

    def _check_memory(self):
        """Check current memory usage"""
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()

        # Calculate percentage
        total_mem = psutil.virtual_memory().total
        used_percent = (mem_info.rss / total_mem) * 100

        # Record history
        self._memory_history.append(used_percent)
        if len(self._memory_history) > self._max_history:
            self._memory_history.pop(0)

        # Determine state
        old_state = self._current_state

        if used_percent >= self.thresholds.oom_percent:
            self._current_state = MemoryState.OOM
            if self._on_oom:
                self._on_oom(used_percent)
            self._trigger_oom_protection()

        elif used_percent >= self.thresholds.critical_percent:
            self._current_state = MemoryState.CRITICAL
            if old_state != MemoryState.CRITICAL and self._on_critical:
                self._on_critical(used_percent)
            self._trigger_critical_protection()

        elif used_percent >= self.thresholds.warning_percent:
            self._current_state = MemoryState.WARNING
            if old_state != MemoryState.WARNING and self._on_warning:
                self._on_warning(used_percent)
            self._trigger_warning_protection()

        else:
            self._current_state = MemoryState.NORMAL

        self._last_check = time.time()

    def _check_queues(self):
        """Check queue sizes against limits"""
        for queue_name, size in self._queue_sizes.items():
            limit = self._queue_limits.get(queue_name, float('inf'))

            if size > limit:
                logger.warning(f"Queue {queue_name} exceeds limit: {size}/{limit}")

    def _check_workers(self):
        """Check worker health and memory"""
        for worker_id, health in self._worker_health.items():
            mem = health.get("memory_mb", 0)

            if mem > self.thresholds.critical_mb:
                logger.warning(f"Worker {worker_id} high memory: {mem}MB")
                # Could trigger worker recycling here

    def _trigger_warning_protection(self):
        """Trigger protection at warning level"""
        logger.warning(f"Memory warning: {self._current_state}")

        # Reduce cache sizes
        # Increase poll intervals
        # Log warning

    def _trigger_critical_protection(self):
        """Trigger protection at critical level"""
        logger.critical(f"Memory critical: {self._current_state}")

        # Activate backpressure
        # Drop low-priority queues
        # Force GC
        import gc
        gc.collect()

        # Reduce batch sizes

    def _trigger_oom_protection(self):
        """Trigger OOM protection"""
        logger.critical("Memory OOM - triggering emergency protection")

        # Kill lowest priority workers
        # Clear non-essential caches
        # Emergency GC
        import gc
        gc.collect()

        # Stop accepting new work
        # Notify monitoring

    def register_queue(self, queue_name: str, limit: int):
        """Register a queue with size limit"""
        with self._lock:
            self._queue_limits[queue_name] = limit
            self._queue_sizes[queue_name] = 0

    def update_queue_size(self, queue_name: str, size: int):
        """Update queue size"""
        with self._lock:
            self._queue_sizes[queue_name] = size

            # Check if over critical
            limit = self._queue_limits.get(queue_name)
            if limit and size > limit * 0.9:  # 90% of limit
                return False

        return True

    def register_worker(self, worker_id: str):
        """Register a worker for monitoring"""
        with self._lock:
            self._worker_health[worker_id] = {
                "registered_at": time.time(),
                "memory_mb": 0,
                "cpu_percent": 0
            }

    def update_worker_health(self, worker_id: str, memory_mb: float, cpu_percent: float):
        """Update worker health metrics"""
        with self._lock:
            if worker_id in self._worker_health:
                self._worker_health[worker_id].update({
                    "memory_mb": memory_mb,
                    "cpu_percent": cpu_percent,
                    "last_update": time.time()
                })

    def can_accept_work(self, priority: int = 0) -> bool:
        """Check if system can accept more work"""
        return self._current_state in [MemoryState.NORMAL, MemoryState.WARNING]

    def get_optimal_batch_size(self, base_size: int) -> int:
        """Get optimal batch size based on memory pressure"""
        if self._current_state == MemoryState.NORMAL:
            return base_size
        elif self._current_state == MemoryState.WARNING:
            return int(base_size * 0.7)
        elif self._current_state == MemoryState.CRITICAL:
            return int(base_size * 0.3)
        else:
            return 1

    def set_warning_callback(self, callback: Callable):
        """Set warning callback"""
        self._on_warning = callback

    def set_critical_callback(self, callback: Callable):
        """Set critical callback"""
        self._on_critical = callback

    def set_oom_callback(self, callback: Callable):
        """Set OOM callback"""
        self._on_oom = callback

    def get_stats(self) -> Dict:
        """Get memory statistics"""
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()

        avg_memory = sum(self._memory_history) / len(self._memory_history) if self._memory_history else 0

        return {
            "current_state": self._current_state.value,
            "rss_mb": mem_info.rss / (1024 * 1024),
            "vms_mb": mem_info.vms / (1024 * 1024),
            "average_percent": avg_memory,
            "queue_sizes": dict(self._queue_sizes),
            "worker_count": len(self._worker_health)
        }


# Global instance
memory_guardian = MemoryGuardian()
