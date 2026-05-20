"""AI gateway policy endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from backend.core.ai_gateway import get_ai_gateway

router = APIRouter(prefix="/ai/gateway", tags=["ai-gateway"])


@router.get("/status")
async def ai_gateway_status() -> Dict[str, Any]:
    return get_ai_gateway().status()
