"""
Resource Manager - Enterprise Resource Management
==========================================

Enterprise resource manager with memory pressure detection,
adaptive throttling, and emergency recovery.
"""

from .enterprise_resource_manager import (
    EnterpriseResourceManager,
    ResourceState,
    PressureLevel,
    ResourceThresholds,
    ResourceSnapshot,
    VectorCache,
    MemoryPressureEvent,
    CPUWatchdog,
    EmergencyCoordinator,
    LowMemoryMode,
    get_enterprise_resource_manager,
    init_enterprise_resource_manager,
)

# Alias for backwards compatibility
ResourceManager = EnterpriseResourceManager

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
]