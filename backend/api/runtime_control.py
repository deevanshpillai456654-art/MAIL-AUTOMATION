"""Runtime profile, service and agent control endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.core.runtime_control import (
    apply_runtime_override,
    clear_runtime_override,
    get_runtime_control,
)

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


@router.get("/modules")
async def get_runtime_modules(_auth=Depends(require_local_auth)):
    from backend.app.router_registry import API_ROUTER_SPECS

    runtime = get_runtime_control()
    return {
        **runtime.snapshot(),
        "modules": runtime.router_status(spec.name for spec in API_ROUTER_SPECS),
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


class LowResourceToggle(BaseModel):
    enabled: bool


@router.get("/low-resource-mode")
async def get_low_resource_mode(_auth=Depends(require_local_auth)):
    runtime = get_runtime_control()
    return {"enabled": runtime.low_resource, "profile": runtime.profile}


@router.post("/low-resource-mode")
async def set_low_resource_mode(body: LowResourceToggle, _auth=Depends(require_local_auth)):
    if body.enabled:
        apply_runtime_override("AIO_LOW_RESOURCE_MODE", "true")
    else:
        clear_runtime_override("AIO_LOW_RESOURCE_MODE")
        clear_runtime_override("AIO_RUNTIME_PROFILE")
    runtime = get_runtime_control()
    return {
        "enabled": runtime.low_resource,
        "profile": runtime.profile,
        "snapshot": runtime.snapshot(),
    }
