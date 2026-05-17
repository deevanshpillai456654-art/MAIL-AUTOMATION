"""
RouteRegistry — dynamic FastAPI route registration for plugins.

Plugins register routes at startup; the API gateway mounts them under
/plugins/{plugin_id}/... so they never collide with core routes.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class PluginRoute:
    plugin_id:   str
    path:        str          # e.g. "/webhooks/inbound"
    method:      str          # GET | POST | PUT | DELETE | PATCH
    handler:     Callable     # async request handler
    tags:        List[str]    = field(default_factory=list)
    summary:     str          = ""
    requires_auth: bool       = True
    tenant_scoped: bool       = True
    rate_limit:  Optional[int] = None  # requests per minute; None = unlimited


class RouteRegistry:
    """Thread-safe registry of plugin-contributed HTTP routes."""

    _instance: Optional["RouteRegistry"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "RouteRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._routes: Dict[str, List[PluginRoute]] = {}  # plugin_id → routes
        self._lock = threading.RLock()

    def register(self, route: PluginRoute) -> None:
        with self._lock:
            self._routes.setdefault(route.plugin_id, []).append(route)
        log.debug(
            "RouteRegistry: registered %s %s for plugin=%s",
            route.method, route.path, route.plugin_id,
        )

    def register_many(self, routes: List[PluginRoute]) -> None:
        for r in routes:
            self.register(r)

    def deregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            removed = len(self._routes.pop(plugin_id, []))
        log.debug("RouteRegistry: deregistered %d routes for plugin=%s", removed, plugin_id)

    def get_routes(self, plugin_id: Optional[str] = None) -> List[PluginRoute]:
        with self._lock:
            if plugin_id:
                return list(self._routes.get(plugin_id, []))
            return [r for routes in self._routes.values() for r in routes]

    def all_plugins_with_routes(self) -> List[str]:
        with self._lock:
            return list(self._routes.keys())
