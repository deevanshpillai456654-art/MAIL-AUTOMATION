"""Local browser session bootstrap endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Response, status

from backend.auth.local_auth import set_local_session_cookie

router = APIRouter(prefix="/session", tags=["session"])


@router.post(
    "/bootstrap",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def bootstrap_local_session() -> Response:
    # No auth dependency — LocalAPIAuthMiddleware already exempts this path
    # via PUBLIC_EXACT_PATHS. The server binds only to 127.0.0.1.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    set_local_session_cookie(response)
    return response


__all__ = ["router"]
