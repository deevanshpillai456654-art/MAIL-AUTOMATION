"""AI gateway policy endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from backend.auth.local_auth import require_local_auth_or_localhost

from backend.core.ai_gateway import get_ai_gateway

router = APIRouter(prefix="/ai/gateway", tags=["ai-gateway"], dependencies=[Depends(require_local_auth_or_localhost)])


@router.get("/status")
async def ai_gateway_status() -> Dict[str, Any]:
    return get_ai_gateway().status()
