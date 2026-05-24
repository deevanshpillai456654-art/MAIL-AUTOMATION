"""
Plugin System - Extensibility
==============================

Plugin system for extensibility:
- Plugin discovery
- Plugin loading
- Plugin lifecycle
- Plugin isolation
- Plugin API
"""

import importlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from backend import config

logger = logging.getLogger("plugin.system")


class PluginState(Enum):
    DISCOVERED = "discovered"
    LOADED = "loaded"
    ACTIVE = "active"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass
class PluginInfo:
    """Plugin information"""
    plugin_id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    dependencies: List[str] = field(default_factory=list)
    state: PluginState = PluginState.DISCOVERED
    loaded_at: float = 0


class Plugin:
    """Base plugin class"""

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.enabled = False

    def on_load(self):
        """Called when plugin loads"""
        pass

    def on_enable(self):
        """Called when plugin enables"""
        pass

    def on_disable(self):
        """Called when plugin disables"""
        pass

    def on_unload(self):
        """Called when plugin unloads"""
        pass


class PluginManager:
    """
    Plugin manager.
    """

    def __init__(self, plugin_dir: str = None):
        self.plugin_dir = Path(plugin_dir or config.DATA_DIR) / "plugins"
        self.plugin_dir.mkdir(parents=True, exist_ok=True)

        self._plugins: Dict[str, Plugin] = {}
        self._plugin_info: Dict[str, PluginInfo] = {}
        self._lock = __import__('threading').RLock()

        logger.info(f"PluginManager initialized: {self.plugin_dir}")

    def discover_plugins(self) -> List[str]:
        """Discover available plugins"""
        discovered = []

        # Scan plugin directory
        for file in self.plugin_dir.glob("*_plugin.py"):
            plugin_id = file.stem.replace("_plugin", "")
            discovered.append(plugin_id)

            info = PluginInfo(
                plugin_id=plugin_id,
                name=plugin_id,
                version="9.7.0",
                state=PluginState.DISCOVERED
            )
            self._plugin_info[plugin_id] = info

        logger.info(f"Discovered {len(discovered)} plugins")
        return discovered

    def load_plugin(self, plugin_id: str) -> bool:
        """Load plugin"""
        with self._lock:
            try:
                # Import plugin module
                module_name = f"{plugin_id}_plugin"
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    self.plugin_dir / f"{module_name}.py"
                )

                if not spec or not spec.loader:
                    return False

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Get plugin class
                class_name = f"{plugin_id.replace('-', '_').title().replace('_', '')}Plugin"

                if hasattr(module, class_name):
                    plugin_class = getattr(module, class_name)
                    plugin = plugin_class(plugin_id)

                    self._plugins[plugin_id] = plugin

                    info = self._plugin_info.get(plugin_id)
                    if info:
                        info.state = PluginState.LOADED
                        info.loaded_at = __import__('time').time()

                    plugin.on_load()

                    logger.info(f"Plugin loaded: {plugin_id}")
                    return True

            except Exception as e:
                logger.error(f"Plugin load error: {e}")

        return False

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enable plugin"""
        plugin = self._plugins.get(plugin_id)

        if not plugin:
            return False

        plugin.enabled = True
        plugin.on_enable()

        info = self._plugin_info.get(plugin_id)
        if info:
            info.state = PluginState.ACTIVE

        logger.info(f"Plugin enabled: {plugin_id}")
        return True

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disable plugin"""
        plugin = self._plugins.get(plugin_id)

        if not plugin:
            return False

        plugin.enabled = False
        plugin.on_disable()

        info = self._plugin_info.get(plugin_id)
        if info:
            info.state = PluginState.DISABLED

        logger.info(f"Plugin disabled: {plugin_id}")
        return True

    def unload_plugin(self, plugin_id: str) -> bool:
        """Unload plugin"""
        plugin = self._plugins.get(plugin_id)

        if plugin:
            plugin.on_unload()
            del self._plugins[plugin_id]

            info = self._plugin_info.get(plugin_id)
            if info:
                info.state = PluginState.DISCOVERED

            logger.info(f"Plugin unloaded: {plugin_id}")
            return True

        return False

    def get_plugin(self, plugin_id: str) -> Optional[Plugin]:
        """Get plugin instance"""
        return self._plugins.get(plugin_id)

    def get_plugin_info(self, plugin_id: str) -> Optional[PluginInfo]:
        """Get plugin info"""
        return self._plugin_info.get(plugin_id)

    def list_plugins(self) -> List[PluginInfo]:
        """List all plugins"""
        return list(self._plugin_info.values())

    def get_stats(self) -> Dict:
        """Get plugin stats"""
        return {
            "total": len(self._plugins),
            "active": sum(1 for p in self._plugins.values() if p.enabled),
            "discovered": len(self._plugin_info)
        }


# Global plugin manager
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """Get global plugin manager"""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager


__all__ = ["PluginManager", "Plugin", "PluginInfo", "PluginState", "get_plugin_manager"]
