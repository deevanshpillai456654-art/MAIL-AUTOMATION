"""
PluginRouteLoader — mounts plugin routes onto a FastAPI app at runtime.

Routes are registered under /plugins/{plugin_id}/{original_path} so they
never clash with core application routes.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from .route_registry import PluginRoute, RouteRegistry

log = logging.getLogger(__name__)

try:
    from fastapi import APIRouter, FastAPI
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


class PluginRouteLoader:
    """
    Loads routes from RouteRegistry and mounts them onto a FastAPI app.

    Usage::

        loader = PluginRouteLoader(app)
        loader.mount_plugin("salesforce")   # after plugin starts
        loader.unmount_plugin("salesforce") # after plugin stops
    """

    def __init__(self, app: Any, *, registry: Optional[RouteRegistry] = None) -> None:
        self._app = app
        self._registry = registry or RouteRegistry.get()
        # Track mounted routers so we can remove them on unmount
        self._mounted: dict[str, Any] = {}

    def mount_all(self) -> None:
        """Mount routes for all plugins currently registered."""
        for plugin_id in self._registry.all_plugins_with_routes():
            self.mount_plugin(plugin_id)

    def mount_plugin(self, plugin_id: str) -> None:
        if not _HAS_FASTAPI:
            log.warning("PluginRouteLoader: FastAPI not available, skipping mount")
            return
        routes = self._registry.get_routes(plugin_id)
        if not routes:
            return
        router = self._build_router(plugin_id, routes)
        prefix = f"/plugins/{plugin_id}"
        self._app.include_router(router, prefix=prefix)
        self._mounted[plugin_id] = router
        log.info(
            "PluginRouteLoader: mounted %d route(s) for plugin=%s at %s",
            len(routes), plugin_id, prefix,
        )

    def unmount_plugin(self, plugin_id: str) -> None:
        """
        Remove routes for a plugin.

        FastAPI doesn't natively support route removal; we rebuild the
        router list from scratch, excluding this plugin's routes.
        This is safe during normal plugin teardown.
        """
        if not _HAS_FASTAPI:
            return
        router = self._mounted.pop(plugin_id, None)
        if router is None:
            return
        prefix = f"/plugins/{plugin_id}"
        self._app.routes = [
            r for r in self._app.routes
            if not (hasattr(r, "path") and r.path.startswith(prefix))
        ]
        log.info("PluginRouteLoader: unmounted routes for plugin=%s", plugin_id)

    def _build_router(self, plugin_id: str, routes: List[PluginRoute]) -> Any:
        from fastapi import APIRouter
        router = APIRouter(tags=[f"plugin:{plugin_id}"])
        for route in routes:
            method = route.method.upper()
            path   = route.path if route.path.startswith("/") else f"/{route.path}"
            kwargs = {
                "path":    path,
                "summary": route.summary or f"{plugin_id} {method} {path}",
            }
            if route.tags:
                kwargs["tags"] = route.tags
            adder = getattr(router, method.lower(), None)
            if adder:
                adder(**kwargs)(route.handler)
            else:
                log.warning("PluginRouteLoader: unknown HTTP method %s for %s", method, path)
        return router
