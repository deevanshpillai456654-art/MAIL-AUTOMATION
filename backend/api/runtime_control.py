"""Runtime profile, service and agent control endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.local_auth import require_local_auth
from backend.core.runtime_control import get_runtime_control

router = APIRouter(prefix="/runtime", tags=["runtime-control"])


@router.get("/profile")
async def get_runtime_profile(_auth=Depends(require_local_auth)):
    return get_runtime_control().snapshot()


@router.get("/services")
async def get_runtime_services(_auth=Depends(require_local_auth)):
    runtime = get_runtime_control()
    return {
        **runtime.snapshot(),
        "services": runtime.service_status(),
    }


@router.get("/agents")
async def get_runtime_agents(_auth=Depends(require_local_auth)):
    runtime = get_runtime_control()
    return {
        **runtime.snapshot(),
        "agents": runtime.agent_status(),
    }


@router.get("/frontend")
async def get_frontend_runtime(_auth=Depends(require_local_auth)):
    runtime = get_runtime_control()
    return {
        "profile": runtime.profile,
        "ai_mode": runtime.ai_mode,
        "limits": runtime.limits,
        "frontend": runtime.frontend_flags(),
    }
