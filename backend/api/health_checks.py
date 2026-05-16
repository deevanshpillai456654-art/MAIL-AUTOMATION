# Health Check Module
# Provides centralized health checking for all system components

import os
import psutil
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    name: str
    status: HealthStatus
    message: str
    metadata: Dict[str, Any]


def check_database_health() -> ComponentHealth:
    """Check database connectivity"""
    try:
        from backend.db.database import get_db
        db = get_db()
        return ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            message="Database connected",
            metadata={"type": "SQLite"}
        )
    except Exception as e:
        return ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database error: {str(e)}",
            metadata={}
        )


def check_memory_health() -> ComponentHealth:
    """Check memory usage"""
    mem = psutil.virtual_memory()
    percent = mem.percent
    
    if percent < 75:
        status = HealthStatus.HEALTHY
    elif percent < 90:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.UNHEALTHY
    
    return ComponentHealth(
        name="memory",
        status=status,
        message=f"Memory usage: {percent:.1f}%",
        metadata={"percent": percent, "available_mb": mem.available / (1024*1024)}
    )


def check_disk_health() -> ComponentHealth:
    """Check disk space"""
    _disk_root = "/" if os.name != "nt" else os.environ.get("SystemDrive", "C:") + os.sep
    disk = psutil.disk_usage(_disk_root)
    percent = disk.percent
    
    if percent < 80:
        status = HealthStatus.HEALTHY
    elif percent < 95:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.UNHEALTHY
    
    return ComponentHealth(
        name="disk",
        status=status,
        message=f"Disk usage: {percent:.1f}%",
        metadata={"percent": percent, "free_gb": disk.free / (1024*1024*1024)}
    )


def check_cpu_health() -> ComponentHealth:
    """Check CPU usage"""
    cpu = psutil.cpu_percent(interval=0.5)
    
    if cpu < 70:
        status = HealthStatus.HEALTHY
    elif cpu < 90:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.UNHEALTHY
    
    return ComponentHealth(
        name="cpu",
        status=status,
        message=f"CPU usage: {cpu:.1f}%",
        metadata={"percent": cpu, "cores": psutil.cpu_count()}
    )


def get_system_health() -> Dict[str, Any]:
    """Get overall system health"""
    checks = [
        check_database_health(),
        check_memory_health(),
        check_disk_health(),
        check_cpu_health()
    ]
    
    unhealthy = [c for c in checks if c.status == HealthStatus.UNHEALTHY]
    degraded = [c for c in checks if c.status == HealthStatus.DEGRADED]
    
    if unhealthy:
        overall = HealthStatus.UNHEALTHY
    elif degraded:
        overall = HealthStatus.DEGRADED
    else:
        overall = HealthStatus.HEALTHY
    
    return {
        "status": overall.value,
        "timestamp": time.time(),
        "components": [
            {"name": c.name, "status": c.status.value, "message": c.message}
            for c in checks
        ]
    }


if __name__ == "__main__":
    health = get_system_health()
    print(f"System Health: {health['status'].upper()}")
    for comp in health["components"]:
        print(f"  {comp['name']}: {comp['status']} - {comp['message']}")