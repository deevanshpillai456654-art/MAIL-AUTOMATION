"""
Resource Manager - Enterprise Resource Management
==========================================

Enterprise resource manager with memory pressure detection,
adaptive throttling, and emergency recovery.
"""

from .enterprise_resource_manager import (
    CPUWatchdog,
    EmergencyCoordinator,
    EnterpriseResourceManager,
    LowMemoryMode,
    MemoryPressureEvent,
    PressureLevel,
    ResourceSnapshot,
    ResourceState,
    ResourceThresholds,
    VectorCache,
    get_enterprise_resource_manager,
    init_enterprise_resource_manager,
)

# Alias for backwards compatibility
ResourceManager = EnterpriseResourceManager

_resource_manager: "EnterpriseResourceManager | None" = None


def get_resource_manager() -> "EnterpriseResourceManager":
    """Return the singleton resource manager, respecting the enterprise_system toggle.

    When AIO_SERVICE_ENTERPRISE_SYSTEM is disabled the instance is created but
    *not* started, keeping it inert so callers can still reference it safely.
    """
    from backend.core.runtime_control import get_runtime_control  # local import avoids circular dep
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
        if get_runtime_control().is_service_enabled("enterprise_system"):
            _resource_manager.start()
    return _resource_manager


__all__ = [
    "EnterpriseResourceManager",
    "ResourceManager",
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
    "get_resource_manager",
]
