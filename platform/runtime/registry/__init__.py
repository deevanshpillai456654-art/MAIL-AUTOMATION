"""Runtime registry subsystem — service registry, capability resolver, plugin discovery."""
from .service_registry import ServiceRegistry, get_service_registry
from .capability_resolver import CapabilityResolver
from .plugin_discovery import PluginDiscovery
from .dependency_resolver import DependencyResolver

__all__ = [
    "ServiceRegistry", "get_service_registry",
    "CapabilityResolver",
    "PluginDiscovery",
    "DependencyResolver",
]
