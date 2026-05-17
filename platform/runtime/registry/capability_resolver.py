"""
CapabilityResolver — resolves which plugin to use for a given capability request.

Supports:
  - First-available resolution
  - Tenant-scoped resolution
  - Priority-ordered resolution
  - Fallback chains
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .service_registry import PluginRegistration, ServiceRegistry

log = logging.getLogger(__name__)


class CapabilityResolver:
    """
    Resolves a capability name to a specific plugin instance or ordered list.

    Usage::

        resolver = CapabilityResolver(ServiceRegistry.instance())

        # Get the best plugin that can sync CRM contacts for tenant T1
        plugin = resolver.best("crm.contacts.sync", tenant_id="T1")
        if plugin:
            ...
    """

    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        capability: str,
        tenant_id: Optional[str] = None,
    ) -> List[PluginRegistration]:
        """Return all plugins providing *capability*, ordered by state (RUNNING first)."""
        providers = self._registry.resolve_capability(capability, tenant_id=tenant_id)
        # Sort: RUNNING > REGISTERED > others
        def sort_key(p: PluginRegistration) -> int:
            return 0 if p.state.value == "running" else 1 if p.state.value == "registered" else 2
        return sorted(providers, key=sort_key)

    def best(
        self,
        capability: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[PluginRegistration]:
        """Return the highest-priority plugin for *capability* or None."""
        providers = self.resolve(capability, tenant_id=tenant_id)
        return providers[0] if providers else None

    def has(self, capability: str, tenant_id: Optional[str] = None) -> bool:
        """Return True if any plugin provides *capability*."""
        return bool(self.resolve(capability, tenant_id=tenant_id))

    def resolve_chain(
        self,
        capabilities: List[str],
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Optional[PluginRegistration]]:
        """
        Resolve a list of capabilities at once.
        Returns {capability: best_plugin_or_None}.
        """
        return {cap: self.best(cap, tenant_id=tenant_id) for cap in capabilities}


class PluginDiscovery:
    """
    Scans a plugins directory for manifests and registers them.

    Separate from PluginLoader so discovery (filesystem) is decoupled
    from loading (Python import).
    """

    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry

    def discover_from_directory(self, plugins_dir: str) -> List[str]:
        """
        Walk *plugins_dir* looking for plugin.json files.
        Registers each plugin manifest into the ServiceRegistry.
        Returns list of discovered plugin_ids.
        """
        import json
        from pathlib import Path
        from .service_registry import PluginRegistration, Capability, PluginState

        root = Path(plugins_dir)
        if not root.exists():
            log.warning("PluginDiscovery: directory %s does not exist", plugins_dir)
            return []

        discovered: List[str] = []
        for manifest_path in sorted(root.glob("*/plugin.json")):
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                capabilities = [
                    Capability(
                        name=c["name"],
                        description=c.get("description", ""),
                        version=c.get("version", "1.0.0"),
                        tags=c.get("tags", []),
                    )
                    for c in data.get("capabilities", [])
                ]
                reg = PluginRegistration(
                    plugin_id=data["plugin_id"],
                    name=data["name"],
                    version=data["version"],
                    capabilities=capabilities,
                    event_types_emitted=data.get("event_types_emitted", []),
                    event_types_consumed=data.get("event_types_consumed", []),
                    provides_routes=data.get("provides_routes", []),
                    provides_ui_widgets=data.get("provides_ui_widgets", []),
                    provides_workflow_nodes=data.get("provides_workflow_nodes", []),
                    metadata={"manifest_path": str(manifest_path)},
                )
                self._registry.register(reg)
                discovered.append(reg.plugin_id)
            except Exception as exc:
                log.error("PluginDiscovery: failed to load %s: %s", manifest_path, exc)
        return discovered
