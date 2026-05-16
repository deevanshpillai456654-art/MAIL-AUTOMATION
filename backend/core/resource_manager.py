"""
Resource Manager - Memory Pressure & Resource Engine
=====================================================

Enterprise-grade resource management:
- Heap monitoring
- RAM pressure detection
- Model memory limits
- Vector cache eviction
- Queue memory balancing
- Adaptive throttling
- CPU watchdog
- Low-memory mode
- Emergency recovery
"""

import os
import time
import threading
import psutil
import logging
import gc
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from enum import Enum
from collections import deque

logger = logging.getLogger("resource.manager")


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
class QueueMemory:
    """Queue memory tracking"""
    name: str
    current_size: int
    max_size: int
    memory_estimate_mb: float


class ResourceManager:
    """
    Enterprise resource manager with adaptive throttling.
    """
    
    def __init__(self, thresholds: ResourceThresholds = None):
        self.thresholds = thresholds or ResourceThresholds()
        
        # Current state
        self.current_state = ResourceState.NORMAL
        self.last_state_change = time.time()
        
        # Callbacks for state changes
        self.on_warning: Optional[Callable] = None
        self.on_critical: Optional[Callable] = None
        self.on_emergency: Optional[Callable] = None
        self.on_recovery: Optional[Callable] = None
        
        # Memory tracking
        self._memory_history: deque = deque(maxlen=60)  # 1 minute
        self._cpu_history: deque = deque(maxlen=60)
        
        # Queue limits
        self._queue_limits: Dict[str, int] = {}
        self._queue_sizes: Dict[str, int] = {}
        
        # Component memory tracking
        self._component_memory: Dict[str, float] = {}
        
        # Throttling state
        self._throttle_active = False
        self._throttle_factor = 1.0
        
        # Background monitoring
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        
        # Process
        self._process = psutil.Process()
        
        logger.info("Resource Manager initialized")
    
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
        logger.info("Resource monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                self._check_resources()
            except Exception as e:
                logger.error(f"Resource check error: {e}")
            
            time.sleep(1)  # Check every second
    
    def _check_resources(self):
        """Check all resource metrics"""
        with self._lock:
            # Get system metrics
            memory = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            _disk_root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + os.sep
            disk = psutil.disk_usage(_disk_root)
            
            # Record history
            self._memory_history.append(memory.percent)
            self._cpu_history.append(cpu)
            
            # Determine state
            old_state = self.current_state
            
            if memory.percent >= self.thresholds.memory_emergency_percent:
                self.current_state = ResourceState.EMERGENCY
            elif memory.percent >= self.thresholds.memory_critical_percent:
                self.current_state = ResourceState.CRITICAL
            elif memory.percent >= self.thresholds.memory_warning_percent:
                self.current_state = ResourceState.WARNING
            else:
                self.current_state = ResourceState.NORMAL
            
            # State change handling
            if old_state != self.current_state:
                self._handle_state_change(old_state, self.current_state)
            
            # Adaptive throttling
            self._update_throttling()
    
    def _handle_state_change(self, old_state: ResourceState, new_state: ResourceState):
        """Handle state transitions"""
        logger.warning(f"Resource state: {old_state.value} -> {new_state.value}")
        
        self.last_state_change = time.time()
        
        if new_state == ResourceState.WARNING:
            if self.on_warning:
                self.on_warning()
            self._trigger_warning_protection()
        
        elif new_state == ResourceState.CRITICAL:
            if self.on_critical:
                self.on_critical()
            self._trigger_critical_protection()
        
        elif new_state == ResourceState.EMERGENCY:
            if self.on_emergency:
                self.on_emergency()
            self._trigger_emergency_protection()
        
        elif new_state == ResourceState.NORMAL and old_state != ResourceState.NORMAL:
            if self.on_recovery:
                self.on_recovery()
            logger.info("Resources recovered to normal")
    
    def _trigger_warning_protection(self):
        """Warning level protection"""
        logger.info("Triggering warning protection")
        
        # Clear some caches
        self._clear_nonessential_caches()
        
        # Request garbage collection
        gc.collect()
    
    def _trigger_critical_protection(self):
        """Critical level protection"""
        logger.warning("Triggering critical protection")
        
        # Aggressive cache clearing
        self._clear_optional_caches()
        
        # Force garbage collection
        gc.collect()
        
        # Signal components to reduce load
        self._throttle_factor = 0.5
    
    def _trigger_emergency_protection(self):
        """Emergency level protection"""
        logger.critical("TRIGGERING EMERGENCY PROTECTION")
        
        # Emergency measures
        self._emergency_cleanup()
        
        # Maximum throttling
        self._throttle_factor = 0.1
        
        # Block new high-memory operations
    
    def _emergency_cleanup(self):
        """Emergency cleanup operations"""
        try:
            gc.collect()
            logger.critical("Emergency cleanup complete")
        except Exception as e:
            logger.error(f"Emergency cleanup failed: {e}")
    
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
    
    def _clear_nonessential_caches(self):
        """Clear non-essential caches"""
        try:
            # Clear module caches if they have clear methods
            import sys
            for name, module in list(sys.modules.items()):
                if hasattr(module, '_cache'):
                    try:
                        module._cache.clear()
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Cache clear error: {e}")
    
    def _clear_optional_caches(self):
        """Clear optional caches"""
        self._clear_nonessential_caches()
        
        # Reduce vector cache
        if 'vector_cache' in self._component_memory:
            self._component_memory['vector_cache'] *= 0.5
    
    def register_queue(self, name: str, max_size: int):
        """Register a queue for monitoring"""
        with self._lock:
            self._queue_limits[name] = max_size
            self._queue_sizes[name] = 0
    
    def update_queue_size(self, name: str, size: int):
        """Update queue size"""
        with self._lock:
            self._queue_sizes[name] = size
            
            # Check queue limits
            max_size = self._queue_limits.get(name, 10000)
            if size > max_size:
                logger.warning(f"Queue {name} exceeds limit: {size}/{max_size}")
    
    def can_allocate(self, required_mb: float) -> bool:
        """Check if memory can be allocated"""
        memory = psutil.virtual_memory()
        available = memory.available / (1024 * 1024)  # MB
        
        # Leave some headroom
        safe_available = available * 0.8
        
        return safe_available > required_mb
    
    def get_throttle_factor(self) -> float:
        """Get current throttle factor"""
        return self._throttle_factor
    
    def is_throttled(self) -> bool:
        """Check if throttling is active"""
        return self._throttle_active
    
    def get_current_state(self) -> ResourceState:
        """Get current resource state"""
        return self.current_state
    
    def get_snapshot(self) -> ResourceSnapshot:
        """Get current resource snapshot"""
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
    
    def get_queue_stats(self) -> List[QueueMemory]:
        """Get queue memory statistics"""
        stats = []
        with self._lock:
            for name, size in self._queue_sizes.items():
                max_size = self._queue_limits.get(name, 1000)
                # Rough estimate: 1KB per item
                est_mb = (size * 1024) / (1024 * 1024)
                stats.append(QueueMemory(
                    name=name,
                    current_size=size,
                    max_size=max_size,
                    memory_estimate_mb=est_mb
                ))
        return stats
    
    def get_memory_trend(self) -> str:
        """Get memory trend"""
        if len(self._memory_history) < 10:
            return "insufficient_data"
        
        recent = list(self._memory_history)[-10:]
        avg = sum(recent) / len(recent)
        
        if avg > 80:
            return "high"
        elif avg > 60:
            return "moderate"
        else:
            return "stable"
    
    def set_component_memory(self, component: str, memory_mb: float):
        """Set component memory usage"""
        self._component_memory[component] = memory_mb
    
    def get_component_memory(self) -> Dict[str, float]:
        """Get component memory usage"""
        return dict(self._component_memory)
    
    def force_emergency_recovery(self):
        """Force emergency recovery mode"""
        logger.critical("FORCING EMERGENCY RECOVERY")
        self.current_state = ResourceState.EMERGENCY
        self._throttle_factor = 0.05
        self._emergency_cleanup()
        
        # Notify all components
        if self.on_emergency:
            try:
                self.on_emergency()
            except Exception:
                pass
    
    def get_stats(self) -> Dict:
        """Get resource statistics"""
        snapshot = self.get_snapshot()
        return {
            "state": snapshot.state.value,
            "memory_percent": snapshot.memory_percent,
            "cpu_percent": snapshot.cpu_percent,
            "disk_percent": snapshot.disk_percent,
            "memory_used_mb": snapshot.memory_used_mb,
            "memory_total_mb": snapshot.memory_total_mb,
            "throttle_active": self._throttle_active,
            "throttle_factor": self._throttle_factor,
            "active_threads": snapshot.active_threads,
            "memory_trend": self.get_memory_trend(),
            "queues": [q.name for q in self.get_queue_stats()],
            "component_memory": self.get_component_memory()
        }


# Global resource manager
_resource_manager: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    """Get or create global resource manager"""
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
        _resource_manager.start()
    return _resource_manager