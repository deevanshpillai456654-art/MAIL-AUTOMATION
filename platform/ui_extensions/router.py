"""
UIExtensionRouter — FastAPI router exposing the UI manifest endpoint.

The frontend calls GET /platform/ui/manifest to get the full list of
plugin-contributed sidebar items, widgets, and routes.

Mount this on the main FastAPI app without modifying core routes::

    from platform.ui_extensions.router import ui_extension_router
    app.include_router(ui_extension_router, prefix="/platform")
"""
from __future__ import annotations

from typing import Any, Dict

try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse

    ui_extension_router = APIRouter(tags=["UI Extensions"])

    @ui_extension_router.get("/ui/manifest")
    async def get_ui_manifest() -> Dict[str, Any]:
        """Return the current UI extension manifest for all installed plugins."""
        from .extension_registry import UIExtensionRegistry
        return UIExtensionRegistry.get().manifest()

    @ui_extension_router.get("/ui/sidebar")
    async def get_sidebar_items() -> Any:
        from .extension_registry import UIExtensionRegistry
        return UIExtensionRegistry.get().get_sidebar_items()

    @ui_extension_router.get("/ui/widgets")
    async def get_widgets(placement: str = "") -> Any:
        from .extension_registry import UIExtensionRegistry
        return UIExtensionRegistry.get().get_widgets(placement or None)

    @ui_extension_router.get("/ui/routes")
    async def get_plugin_routes() -> Any:
        from .extension_registry import UIExtensionRegistry
        return UIExtensionRegistry.get().get_routes()

except ImportError:
    # FastAPI not available — provide a no-op placeholder
    ui_extension_router = None  # type: ignore[assignment]
