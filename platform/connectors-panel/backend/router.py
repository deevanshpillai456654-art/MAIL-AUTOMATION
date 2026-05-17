"""
Connector & Plugin Panel – Main Router

Mount into your FastAPI app:

    from platform.connectors_panel.backend.router import setup
    panel_router = setup()
    app.include_router(panel_router)

All sub-routers are mounted under /api/connector-panel.
"""
from __future__ import annotations

import logging
from pathlib import Path
from fastapi import APIRouter, Depends, Response, status
from fastapi.staticfiles import StaticFiles

from backend.auth.local_auth import require_local_auth, set_local_session_cookie

log = logging.getLogger(__name__)

from .connectors import router as connectors_router
from .connector_engine import router as engine_router, public_router as engine_public_router
from .crm import router as crm_router
from .db import init_panel_db
from .erp import router as erp_router
from .events import router as events_router
from .health import router as health_router
from .logs import router as logs_router
from .marketplace import router as marketplace_router
from .oauth import router as oauth_router
from .plugins import router as plugins_router
from .queues import router as queues_router
from .support import router as support_router
from .tracking import router as tracking_router
from .webhooks import router as webhooks_router, public_router as webhooks_public_router
from .workflows import router as workflows_router
from ..shared.constants import CONNECTOR_PANEL_VERSION

# ---------------------------------------------------------------------------
# Root router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/connector-panel",
    tags=["connector-panel"],
)

_AUTH = [Depends(require_local_auth)]


@router.get("/", summary="Panel status and version", dependencies=_AUTH)
async def panel_root():
    return {
        "name": "MailPilot Connector & Plugin Panel",
        "version": CONNECTOR_PANEL_VERSION,
        "status": "running",
        "endpoints": {
            "connectors":  "/api/connector-panel/connectors",
            "marketplace": "/api/connector-panel/marketplace",
            "plugins":     "/api/connector-panel/plugins",
            "oauth":       "/api/connector-panel/oauth",
            "webhooks":    "/api/connector-panel/webhooks",
            "queues":      "/api/connector-panel/queues",
            "logs":        "/api/connector-panel/logs",
            "health":      "/api/connector-panel/health",
            "events":      "/api/connector-panel/events",
            "engine":      "/api/connector-panel/engine",
        },
    }


@router.post(
    "/session",
    include_in_schema=False,
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_AUTH,
)
async def bootstrap_panel_session() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_local_session_cookie(response)
    return response


# Public sub-routers: inbound webhooks and OAuth callbacks from external providers.
# These must NOT carry the local-auth dependency — external systems cannot present it.
router.include_router(webhooks_public_router)
router.include_router(engine_public_router)

# All remaining sub-routers require the local API token.
router.include_router(connectors_router, dependencies=_AUTH)
router.include_router(marketplace_router, dependencies=_AUTH)
router.include_router(plugins_router, dependencies=_AUTH)
router.include_router(oauth_router, dependencies=_AUTH)
router.include_router(webhooks_router, dependencies=_AUTH)
router.include_router(queues_router, dependencies=_AUTH)
router.include_router(logs_router, dependencies=_AUTH)
router.include_router(health_router, dependencies=_AUTH)
router.include_router(events_router, dependencies=_AUTH)
router.include_router(engine_router, dependencies=_AUTH)
# Enterprise modules
router.include_router(erp_router, dependencies=_AUTH)
router.include_router(crm_router, dependencies=_AUTH)
router.include_router(tracking_router, dependencies=_AUTH)
router.include_router(workflows_router, dependencies=_AUTH)
router.include_router(support_router, dependencies=_AUTH)


# ---------------------------------------------------------------------------
# Setup function
# ---------------------------------------------------------------------------

def setup(db_path: str | None = None) -> APIRouter:
    """
    Initialise the connector panel database and return the configured router.

    Call this once at application startup:

        from platform.connectors_panel.backend.router import setup
        panel_router = setup()
        app.include_router(panel_router)

    Args:
        db_path: Optional explicit path for the SQLite database.
                 Defaults to the CONNECTOR_PANEL_DB_PATH env var or
                 platform/connectors_panel.db relative to the project root.

    Returns:
        The fully configured APIRouter ready to be included in a FastAPI app.
    """
    init_panel_db(db_path)
    _init_connector_sdk()
    return router


def _init_connector_sdk() -> None:
    """Initialise the ConnectorRegistry and start the background worker."""
    try:
        from .db import get_panel_db
        from ..connectors.sdk.registry import ConnectorRegistry
        from ..connectors.sdk.worker import init_worker

        db = get_panel_db()
        registry = ConnectorRegistry.get()
        registry.init(db)
        worker = init_worker(db, registry)
        worker.start()
        log.info("Connector SDK initialised — registry: %d connectors, worker: started",
                 len(registry.list_manifests()))
    except Exception as exc:
        log.warning("Connector SDK init failed (non-fatal): %s", exc)


def setup_connector_panel(app, *, db_path: str | None = None) -> None:
    """
    Full one-call setup: initialise DB, mount API router, and serve the
    frontend SPA at /connectors-panel.

    Usage
    -----
    ```python
    from fastapi import FastAPI
    from platform.connectors_panel.backend.router import setup_connector_panel

    app = FastAPI()
    setup_connector_panel(app)   # add to your lifespan or startup
    ```
    """
    configured_router = setup(db_path)
    app.include_router(configured_router)

    _frontend = Path(__file__).resolve().parents[1] / "frontend"
    if _frontend.exists():
        try:
            app.mount(
                "/connectors-panel",
                StaticFiles(directory=str(_frontend), html=True),
                name="connector_panel_ui",
            )
            log.info("Connector Panel UI at /connectors-panel")
        except Exception as exc:
            log.warning("Could not mount Connector Panel UI: %s", exc)
    else:
        log.warning("Connector Panel frontend not found at %s", _frontend)

    log.info("MailPilot Connector Panel ready — API: /api/connector-panel")
