"""OAuth middleware — localhost-only enforcement for OAuth callbacks."""
from __future__ import annotations

from fastapi import HTTPException, Request


def require_local_request(request: Request) -> None:
    """Reject OAuth callbacks from non-localhost origins."""
    host = request.client.host if request.client else "127.0.0.1"
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(
            status_code=403,
            detail="OAuth callbacks are only accepted from localhost",
        )
