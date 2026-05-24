import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from backend.auth.local_auth import require_local_auth_or_localhost

logger = logging.getLogger("api.system")
router = APIRouter(dependencies=[Depends(require_local_auth_or_localhost)])


@router.get("/enterprise/status")
async def enterprise_status(request: Request) -> Dict[str, Any]:
    enterprise_system = getattr(request.app.state, "enterprise_system", None)
    if not enterprise_system:
        return {
            "status": "uninitialized",
            "message": "EnterpriseSystem is not available in application state"
        }

    return {
        "status": "ok",
        "enterprise_system": enterprise_system.get_status()
    }


@router.get("/enterprise/diagnostics")
async def enterprise_diagnostics(request: Request) -> Dict[str, Any]:
    enterprise_system = getattr(request.app.state, "enterprise_system", None)
    if not enterprise_system:
        return {
            "status": "uninitialized",
            "message": "EnterpriseSystem diagnostics are not available"
        }

    return {
        "status": "ok",
        "diagnostics": enterprise_system.get_diagnostics()
    }
