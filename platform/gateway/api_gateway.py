"""
APIGateway — plugin-aware HTTP gateway that wraps the core FastAPI app.

Applies the middleware stack and exposes helpers for plugins to register
routes at startup without touching the core application.

Usage::

    gateway = APIGateway(core_app)
    gateway.apply_middleware()

    # After a plugin starts:
    gateway.add_plugin_routes("salesforce")

    # After a plugin stops:
    gateway.remove_plugin_routes("salesforce")
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from .middleware          import AuthMiddleware, RateLimitMiddleware, TenantMiddleware, TracingMiddleware
from .plugin_route_loader import PluginRouteLoader
from .route_registry      import PluginRoute, RouteRegistry

log = logging.getLogger(__name__)


class APIGateway:
    """
    Thin orchestrator that owns:
      - middleware application order
      - dynamic plugin route mounting / unmounting
      - route registry access
    """

    def __init__(
        self,
        app: Any,
        *,
        registry:         Optional[RouteRegistry] = None,
        verify_token:     Optional[Callable[[str], Optional[dict]]] = None,
        requests_per_min: int = 600,
        auth_skip_paths:  Optional[List[str]] = None,
    ) -> None:
        self._app     = app
        self._registry = registry or RouteRegistry.get()
        self._loader   = PluginRouteLoader(app, registry=self._registry)
        self._middleware_applied = False

        self._verify_token     = verify_token
        self._requests_per_min = requests_per_min
        self._auth_skip_paths  = auth_skip_paths or []

    # ── Middleware ────────────────────────────────────────────────────────

    def apply_middleware(self) -> None:
        """
        Wrap the app with the full middleware stack.

        Order (outermost → innermost):
          TracingMiddleware → TenantMiddleware → RateLimitMiddleware → AuthMiddleware
        """
        if self._middleware_applied:
            return
        app = self._app
        app.add_middleware(AuthMiddleware,
                           verify_token=self._verify_token,
                           skip_paths=self._auth_skip_paths)
        app.add_middleware(RateLimitMiddleware,
                           requests_per_minute=self._requests_per_min)
        app.add_middleware(TenantMiddleware)
        app.add_middleware(TracingMiddleware)
        self._middleware_applied = True
        log.info("APIGateway: middleware stack applied")

    # ── Plugin routes ─────────────────────────────────────────────────────

    def register_route(self, route: PluginRoute) -> None:
        """Register a single route then immediately mount it."""
        self._registry.register(route)
        self._loader.mount_plugin(route.plugin_id)

    def add_plugin_routes(self, plugin_id: str) -> None:
        """Mount all routes registered by a specific plugin."""
        self._loader.mount_plugin(plugin_id)

    def remove_plugin_routes(self, plugin_id: str) -> None:
        """Unmount routes and remove them from the registry."""
        self._loader.unmount_plugin(plugin_id)
        self._registry.deregister_plugin(plugin_id)

    def mount_all_registered(self) -> None:
        """Mount routes for every plugin currently in the registry."""
        self._loader.mount_all()

    # ── Introspection ─────────────────────────────────────────────────────

    def list_plugin_routes(self, plugin_id: Optional[str] = None) -> List[dict]:
        routes = self._registry.get_routes(plugin_id)
        return [
            {
                "plugin_id": r.plugin_id,
                "method":    r.method,
                "path":      f"/plugins/{r.plugin_id}{r.path}",
                "summary":   r.summary,
                "auth":      r.requires_auth,
            }
            for r in routes
        ]
