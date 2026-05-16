"""AI Automation Platform – Main Router."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.staticfiles import StaticFiles

from .db import init_ai_automation_db
from .workflows import router as workflows_router
from .executions import router as executions_router
from .approvals import router as approvals_router
from .ai_providers import router as ai_router
from .analytics import router as analytics_router
from .search import router as search_router
from .ocr_enhanced import router as ocr_router

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-automation", tags=["ai-automation"])


@router.get("/", summary="Platform status")
async def platform_root():
    return {
        "name": "MailPilot AI Automation Platform",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "workflows":  "/api/ai-automation/workflows",
            "executions": "/api/ai-automation/executions",
            "approvals":  "/api/ai-automation/approvals",
            "ai":         "/api/ai-automation/ai",
            "ocr":        "/api/ai-automation/ocr",
            "analytics":  "/api/ai-automation/analytics",
            "search":     "/api/ai-automation/search",
        },
    }


router.include_router(workflows_router)
router.include_router(executions_router)
router.include_router(approvals_router)
router.include_router(ai_router)
router.include_router(ocr_router)
router.include_router(analytics_router)
router.include_router(search_router)


def setup(db_path: str | None = None) -> APIRouter:
    init_ai_automation_db(db_path)
    return router


def setup_ai_automation(app, *, db_path: str | None = None) -> None:
    """
    One-call setup: initialise DB, mount API router, serve frontend SPA.

    Usage::

        from platform.ai_automation.backend.router import setup_ai_automation
        setup_ai_automation(app)
    """
    configured_router = setup(db_path)
    app.include_router(configured_router)

    _frontend = Path(__file__).resolve().parents[1] / "frontend"
    if _frontend.exists():
        try:
            app.mount(
                "/ai-automation",
                StaticFiles(directory=str(_frontend), html=True),
                name="ai_automation_ui",
            )
            log.info("AI Automation UI at /ai-automation")
        except Exception as exc:
            log.warning("Could not mount AI Automation UI: %s", exc)
    else:
        log.warning("AI Automation frontend not found at %s", _frontend)

    log.info("MailPilot AI Automation Platform ready — API: /api/ai-automation")
