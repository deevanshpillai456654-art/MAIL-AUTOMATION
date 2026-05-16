from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.runtime_version import APP_VERSION, DISPLAY_VERSION


STATIC_PAGE_ROUTE_PATHS = (
    "/dashboard",
    "/assistant",
    "/setup",
    "/ai",
    "/ai-command-center.js",
    "/admin",
    "/security",
    "/taskpane.html",
    "/favicon.ico",
    "/",
)


@dataclass(frozen=True)
class DashboardPaths:
    project_root: Path
    dashboard: Path
    outlook: Path


def resolve_dashboard_paths(project_root: Path | None = None) -> DashboardPaths:
    root = project_root or Path(__file__).resolve().parents[2]
    dashboard = root / "backend" / "dashboard"
    outlook = root / "outlook-addin"
    if not outlook.exists():
        outlook = root / "extensions" / "outlook"
    return DashboardPaths(project_root=root, dashboard=dashboard, outlook=outlook)


def register_static_dashboard_routes(
    app: FastAPI,
    project_root: Path | None = None,
) -> DashboardPaths:
    paths = resolve_dashboard_paths(project_root)
    dashboard_path = paths.dashboard
    outlook_path = paths.outlook

    if dashboard_path.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_path)), name="dashboard")
    if outlook_path.exists():
        app.mount("/outlook", StaticFiles(directory=str(outlook_path)), name="outlook_addin")
        icons_path = outlook_path / "icons"
        if icons_path.exists():
            app.mount("/icons", StaticFiles(directory=str(icons_path)), name="outlook_icons")

    @app.get("/dashboard")
    async def dashboard_page():
        return FileResponse(str(dashboard_path / "index.html"))

    @app.get("/assistant")
    async def assistant_page():
        """AI-powered guided troubleshooting and admin support assistant."""
        return FileResponse(str(dashboard_path / "assistant.html"))

    @app.get("/setup")
    async def setup_page():
        f = dashboard_path / "setup.html"
        return FileResponse(str(f)) if f.exists() else {"message": "Setup wizard not found"}

    @app.get("/ai")
    async def ai_page():
        f = dashboard_path / "ai-command-center.html"
        return FileResponse(str(f)) if f.exists() else {"message": "AI command center not found"}

    @app.get("/ai-command-center.js")
    async def ai_script():
        f = dashboard_path / "ai-command-center.js"
        return FileResponse(str(f), media_type="application/javascript") if f.exists() else {"message": "Not found"}

    @app.get("/admin")
    async def admin_page():
        f = dashboard_path / "admin.html"
        return FileResponse(str(f)) if f.exists() else FileResponse(str(dashboard_path / "index.html"))

    @app.get("/security")
    async def scam_panel_page():
        f = dashboard_path / "scam-panel.html"
        return FileResponse(str(f)) if f.exists() else FileResponse(str(dashboard_path / "index.html"))

    @app.get("/taskpane.html")
    async def outlook_taskpane():
        f = outlook_path / "taskpane.html"
        return FileResponse(str(f)) if f.exists() else {"message": "Outlook taskpane not found"}

    @app.get("/favicon.ico")
    async def favicon():
        return Response(content=b"", media_type="image/x-icon")

    @app.get("/")
    async def root():
        return {
            "service": DISPLAY_VERSION,
            "version": APP_VERSION,
            "status": "running",
            "docs": "/docs",
        }

    # ── Connector & Plugin Panel ─────────────────────────────────────────────
    try:
        from backend.app.connector_panel_bridge import register_connector_panel
        register_connector_panel(app)
    except Exception as _cp_err:
        import logging as _log
        _log.getLogger(__name__).warning("Connector panel not loaded: %s", _cp_err)

    return paths


__all__ = [
    "DashboardPaths",
    "STATIC_PAGE_ROUTE_PATHS",
    "register_static_dashboard_routes",
    "resolve_dashboard_paths",
]
