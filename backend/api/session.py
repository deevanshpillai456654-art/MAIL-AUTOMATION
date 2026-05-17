"""Local browser session bootstrap endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status

from backend.auth.local_auth import require_local_auth, set_local_session_cookie

router = APIRouter(prefix="/session", tags=["session"])


@router.post(
    "/bootstrap",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_local_auth)],
)
async def bootstrap_local_session() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_local_session_cookie(response)
    return response


__all__ = ["router"]
