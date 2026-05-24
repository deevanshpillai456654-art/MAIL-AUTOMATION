"""
System Health Dashboard
=====================

Provides comprehensive system health data for the admin dashboard.
"""

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict

import psutil


@dataclass
class HealthSnapshot:
    """Snapshot of system health"""
    timestamp: float
    status: str
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    disk_percent: float
    disk_free_gb: float
    threads: int
    open_connections: int
    uptime_seconds: float


class SystemHealthMonitor:
    """Real-time system health monitoring"""

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

        self._start_time = time.time()
        self._process = psutil.Process()
        self._initialized = True

    @property
    def uptime(self) -> float:
        return time.time() - self._start_time

    def get_snapshot(self) -> HealthSnapshot:
        """Get current health snapshot"""
        memory = psutil.virtual_memory()
        _disk_root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + os.sep
        disk = psutil.disk_usage(_disk_root)

        return HealthSnapshot(
            timestamp=time.time(),
            status="healthy",
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_percent=memory.percent,
            memory_used_mb=memory.used / (1024*1024),
            memory_available_mb=memory.available / (1024*1024),
            disk_percent=disk.percent,
            disk_free_gb=disk.free / (1024*1024*1024),
            threads=threading.active_count(),
            open_connections=len(self._process.connections()),
            uptime_seconds=self.uptime
        )

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get dashboard-ready health data"""
        snapshot = self.get_snapshot()

        # Determine status
        if snapshot.memory_percent > 95 or snapshot.disk_percent > 95:
            status = "critical"
        elif snapshot.memory_percent > 85 or snapshot.disk_percent > 90:
            status = "warning"
        else:
            status = "healthy"

        return {
            "status": status,
            "timestamp": snapshot.timestamp,
            "system": {
                "cpu": {
                    "percent": snapshot.cpu_percent,
                    "status": "ok" if snapshot.cpu_percent < 80 else "warning" if snapshot.cpu_percent < 90 else "critical"
                },
                "memory": {
                    "percent": snapshot.memory_percent,
                    "used_mb": round(snapshot.memory_used_mb, 1),
                    "available_mb": round(snapshot.memory_available_mb, 1),
                    "status": "ok" if snapshot.memory_percent < 75 else "warning" if snapshot.memory_percent < 85 else "critical"
                },
                "disk": {
                    "percent": snapshot.disk_percent,
                    "free_gb": round(snapshot.disk_free_gb, 1),
                    "status": "ok" if snapshot.disk_percent < 80 else "warning" if snapshot.disk_percent < 90 else "critical"
                }
            },
            "runtime": {
                "threads": snapshot.threads,
                "connections": snapshot.open_connections,
                "uptime_seconds": round(snapshot.uptime_seconds, 1),
                "uptime_human": self._format_uptime(snapshot.uptime_seconds)
            }
        }

    def _format_uptime(self, seconds: float) -> str:
        """Format uptime as human-readable string"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)

        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"


def get_health_monitor() -> SystemHealthMonitor:
    """Get the health monitor singleton"""
    return SystemHealthMonitor()


# Export for easy use
__all__ = [
    "SystemHealthMonitor",
    "HealthSnapshot",
    "get_health_monitor"
]
