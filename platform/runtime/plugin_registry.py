from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from sdk.models import PluginManifest, PluginStatus

@dataclass
class RegisteredPlugin:
    manifest: PluginManifest
    status: PluginStatus = PluginStatus.REGISTERED
    error: Optional[str] = None

class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: Dict[str, RegisteredPlugin] = {}

    def register(self, manifest: PluginManifest) -> RegisteredPlugin:
        item = RegisteredPlugin(manifest=manifest)
        if manifest.enabled_by_default:
            item.status = PluginStatus.ENABLED
        self._plugins[manifest.plugin_id] = item
        return item

    def enable(self, plugin_id: str) -> None:
        self._plugins[plugin_id].status = PluginStatus.ENABLED
        self._plugins[plugin_id].error = None

    def disable(self, plugin_id: str) -> None:
        self._plugins[plugin_id].status = PluginStatus.DISABLED

    def fail(self, plugin_id: str, error: str) -> None:
        self._plugins[plugin_id].status = PluginStatus.FAILED
        self._plugins[plugin_id].error = error

    def get(self, plugin_id: str) -> RegisteredPlugin | None:
        return self._plugins.get(plugin_id)

    def list(self) -> List[RegisteredPlugin]:
        return list(self._plugins.values())

    def health_summary(self) -> Dict[str, int]:
        summary = {"registered": 0, "enabled": 0, "disabled": 0, "failed": 0}
        for plugin in self._plugins.values():
            summary[plugin.status.value] += 1
        return summary
