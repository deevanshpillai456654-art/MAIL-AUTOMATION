"""Optional API router for manual mounting only.

This file does not auto-register with the MailPilot core app. If the existing backend wants to expose
platform APIs, mount this router manually from the current app's own routing system.
"""
try:
    from fastapi import APIRouter
except Exception:  # pragma: no cover
    APIRouter = None

if APIRouter:
    router = APIRouter(prefix="/api/platform", tags=["platform"])

    @router.get("/health")
    def platform_health():
        return {"status": "ready", "scope": "platform-only", "core_app_modified": False}
else:
    router = None
