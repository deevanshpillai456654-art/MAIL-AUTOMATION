from __future__ import annotations
from typing import Dict, List
from runtime.plugin_registry import PluginRegistry

class RuntimeHealthMonitor:
    def __init__(self, registry: PluginRegistry) -> None:
        self.registry = registry

    def snapshot(self) -> Dict[str, object]:
        plugins = self.registry.list()
        return {
            "status": "healthy" if not any(p.status.value == "failed" for p in plugins) else "degraded",
            "summary": self.registry.health_summary(),
            "plugins": [
                {
                    "plugin_id": p.manifest.plugin_id,
                    "name": p.manifest.name,
                    "version": p.manifest.version,
                    "status": p.status.value,
                    "error": p.error,
                }
                for p in plugins
            ],
        }
