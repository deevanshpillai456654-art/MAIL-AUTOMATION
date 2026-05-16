from __future__ import annotations
from typing import Any, Dict, List

class PluginLifecycle:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    def on_load(self, plugin_id: str) -> None:
        self.events.append({"plugin_id": plugin_id, "hook": "on_load"})

    def on_enable(self, plugin_id: str) -> None:
        self.events.append({"plugin_id": plugin_id, "hook": "on_enable"})

    def on_disable(self, plugin_id: str) -> None:
        self.events.append({"plugin_id": plugin_id, "hook": "on_disable"})

    def on_error(self, plugin_id: str, error: str) -> None:
        self.events.append({"plugin_id": plugin_id, "hook": "on_error", "error": error})
