"""
Enterprise Resource Manager - Advanced Resource Management
=================================================

Comprehensive resource management with:
- Memory pressure detection
- Vector cache management  
- CPU monitoring
- Emergency recovery
- Adaptive throttling
"""

import gc
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

import psutil

logger = logging.getLogger("enterprise.resource.manager")


class ResourceState(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class PressureLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


@dataclass
class ResourceThresholds:
    """Configurable resource thresholds"""
    memory_warning_percent: float = 75.0
    memory_critical_percent: float = 85.0
    memory_emergency_percent: float = 95.0
    cpu_warning_percent: float = 80.0
    cpu_critical_percent: float = 90.0
    disk_warning_percent: float = 85.0
    disk_critical_percent: float = 95.0
    queue_warning_count: int = 1000
    queue_critical_count: int = 5000


@dataclass
class ResourceSnapshot:
    """Resource state snapshot"""
    timestamp: float
    memory_used_mb: float
    memory_total_mb: float
    memory_percent: float
    cpu_percent: float
    disk_percent: float
    state: ResourceState
    active_threads: int
    open_connections: int


@dataclass
class VectorCache:
    """Vector embedding cache"""
    cache_id: str
    max_size: int
    vectors: Dict[str, List[float]] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class MemoryPressureEvent:
    """Memory pressure event"""
    event_id: str
    level: PressureLevel
    memory_percent: float
    timestamp: float = field(default_factory=time.time)


class CPUWatchdog:
    """CPU usage watchdog"""
    def __init__(self, threshold: float = 90.0):
        self.threshold = threshold
        self._process = psutil.Process()

    def is_overloaded(self) -> bool:
        return psutil.cpu_percent(interval=0.1) > self.threshold


class EmergencyCoordinator:
    """Emergency coordination"""
    def __init__(self):
        self._lock = threading.Lock()
        self._emergency_active = False

    def activate(self):
        with self._lock:
            self._emergency_active = True
            gc.collect()

    def deactivate(self):
        with self._lock:
            self._emergency_active = False

    def is_active(self) -> bool:
        return self._emergency_active


class LowMemoryMode:
    """Low memory mode handler"""
    def __init__(self, threshold: float = 85.0):
        self.threshold = threshold

    def should_activate(self) -> bool:
        return psutil.virtual_memory().percent > self.threshold


class EnterpriseResourceManager:
    """
    Enterprise resource manager with adaptive throttling.
    """

    def __init__(self, thresholds: ResourceThresholds = None):
        self.thresholds = thresholds or ResourceThresholds()
        self.current_state = ResourceState.NORMAL
        self.last_state_change = time.time()

        self.on_warning: Optional[Callable] = None
        self.on_critical: Optional[Callable] = None
        self.on_emergency: Optional[Callable] = None
        self.on_recovery: Optional[Callable] = None

        self._memory_history: deque = deque(maxlen=60)
        self._cpu_history: deque = deque(maxlen=60)
        self._queue_limits: Dict[str, int] = {}
        self._queue_sizes: Dict[str, int] = {}
        self._component_memory: Dict[str, float] = {}

        self._throttle_active = False
        self._throttle_factor = 1.0

        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._process = psutil.Process()

        logger.info("EnterpriseResourceManager initialized")

    def start(self):
        """Start resource monitoring"""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Resource monitoring started")

    def stop(self):
        """Stop resource monitoring"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def _monitor_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                self._check_resources()
            except Exception as e:
                logger.error(f"Resource check error: {e}")
            time.sleep(1)

    def _check_resources(self):
        """Check all resource metrics"""
        with self._lock:
            memory = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            _disk_root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + os.sep
            disk = psutil.disk_usage(_disk_root)

            self._memory_history.append(memory.percent)
            self._cpu_history.append(cpu)

            old_state = self.current_state

            if memory.percent >= self.thresholds.memory_emergency_percent:
                self.current_state = ResourceState.EMERGENCY
            elif memory.percent >= self.thresholds.memory_critical_percent:
                self.current_state = ResourceState.CRITICAL
            elif memory.percent >= self.thresholds.memory_warning_percent:
                self.current_state = ResourceState.WARNING
            else:
                self.current_state = ResourceState.NORMAL

            if old_state != self.current_state:
                self._handle_state_change(old_state, self.current_state)

            self._update_throttling()

    def _handle_state_change(self, old_state: ResourceState, new_state: ResourceState):
        """Handle state transitions"""
        logger.warning(f"Resource state: {old_state.value} -> {new_state.value}")
        self.last_state_change = time.time()

        if new_state == ResourceState.WARNING and self.on_warning:
            self.on_warning()
        elif new_state == ResourceState.CRITICAL and self.on_critical:
            self.on_critical()
        elif new_state == ResourceState.EMERGENCY and self.on_emergency:
            self.on_emergency()
        elif new_state == ResourceState.NORMAL and old_state != ResourceState.NORMAL:
            if self.on_recovery:
                self.on_recovery()

    def _update_throttling(self):
        """Update throttling based on state"""
        if self.current_state == ResourceState.EMERGENCY:
            self._throttle_active = True
            self._throttle_factor = 0.1
        elif self.current_state == ResourceState.CRITICAL:
            self._throttle_active = True
            self._throttle_factor = 0.3
        elif self.current_state == ResourceState.WARNING:
            self._throttle_active = True
            self._throttle_factor = 0.7
        else:
            self._throttle_active = False
            self._throttle_factor = 1.0

    def can_allocate(self, required_mb: float) -> bool:
        """Check if memory can be allocated"""
        memory = psutil.virtual_memory()
        available = memory.available / (1024 * 1024)
        safe_available = available * 0.8
        return safe_available > required_mb

    def get_throttle_factor(self) -> float:
        return self._throttle_factor

    def is_throttled(self) -> bool:
        return self._throttle_active

    def get_current_state(self) -> ResourceState:
        return self.current_state

    def get_snapshot(self) -> ResourceSnapshot:
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        _disk_root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + os.sep
        disk = psutil.disk_usage(_disk_root)

        return ResourceSnapshot(
            timestamp=time.time(),
            memory_used_mb=memory.used / (1024 * 1024),
            memory_total_mb=memory.total / (1024 * 1024),
            memory_percent=memory.percent,
            cpu_percent=cpu,
            disk_percent=disk.percent,
            state=self.current_state,
            active_threads=threading.active_count(),
            open_connections=len(self._process.connections())
        )

    def get_stats(self) -> Dict:
        snapshot = self.get_snapshot()
        return {
            "state": snapshot.state.value,
            "memory_percent": snapshot.memory_percent,
            "cpu_percent": snapshot.cpu_percent,
            "throttle_active": self._throttle_active,
            "throttle_factor": self._throttle_factor,
        }


def get_enterprise_resource_manager() -> EnterpriseResourceManager:
    """Get global enterprise resource manager"""
    global _enterprise_resource_manager
    if _enterprise_resource_manager is None:
        _enterprise_resource_manager = EnterpriseResourceManager()
        _enterprise_resource_manager.start()
    return _enterprise_resource_manager


def init_enterprise_resource_manager():
    """Initialize enterprise resource manager"""
    get_enterprise_resource_manager()


_enterprise_resource_manager: Optional[EnterpriseResourceManager] = None


# Export all classes
__all__ = [
    "EnterpriseResourceManager",
    "ResourceState",
    "PressureLevel",
    "ResourceThresholds",
    "ResourceSnapshot",
    "VectorCache",
    "MemoryPressureEvent",
    "CPUWatchdog",
    "EmergencyCoordinator",
    "LowMemoryMode",
    "get_enterprise_resource_manager",
    "init_enterprise_resource_manager",
]
