"""Local API token authentication.

Generates a random per-installation token stored in DATA_DIR/local_api.key on
first use. All sensitive endpoints require this token via:
  - X-Local-Token: <token>
  - Authorization: Bearer <token>

The token is stable across restarts. The Electron desktop app injects it as a
default header in the embedded webview. Callers can read the token from the key
file at DATA_DIR/local_api.key (mode 0o600).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Cookie, Header, HTTPException, Request, Response, status

from backend import config

LOCAL_SESSION_COOKIE = "aio_local_session"


def _token_path() -> Path:
    return Path(config.DATA_DIR) / "local_api.key"


def _load_or_create() -> str:
    """Load the local API token, generating one atomically if absent.

    Two workers cold-starting in parallel could both observe ``path.exists()``
    as False and each generate + write a different token, the second winning
    and orphaning the first worker's in-memory copy. Open the file with the
    exclusive-create flag (``'xb'``) so only one writer can succeed; the
    loser re-reads the winner's token.
    """
    path = _token_path()
    for _ in range(2):
        if path.exists():
            try:
                token = path.read_text("utf-8").strip()
                if len(token) >= 32:
                    return token
            except OSError:
                pass
        token = secrets.token_hex(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "xb") as fh:
                fh.write(token.encode("utf-8"))
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return token
        except FileExistsError:
            # Lost the create race — another worker wrote first; loop re-reads.
            continue
    return token


_LOCAL_TOKEN: Optional[str] = None


def get_local_token() -> str:
    """Return (generating if needed) the per-installation API token."""
    global _LOCAL_TOKEN
    if _LOCAL_TOKEN is None:
        _LOCAL_TOKEN = _load_or_create()
    return _LOCAL_TOKEN


def _validate_token(token: str) -> None:
    expected = get_local_token()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid local API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _is_valid_token(token: Optional[str]) -> bool:
    if not token:
        return False
    return secrets.compare_digest(str(token), get_local_token())


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return None


def request_has_valid_local_auth(request: Request) -> bool:
    """Return True when request carries the local API credential."""
    return (
        _is_valid_token(request.headers.get("X-Local-Token"))
        or _is_valid_token(_bearer_token(request.headers.get("Authorization")))
        or _is_valid_token(request.cookies.get(LOCAL_SESSION_COOKIE))
    )


def _cookie_secure_flag() -> bool:
    """Return True when the session cookie should be marked Secure.

    Defaults to False because the local-first desktop service binds to
    127.0.0.1 with no HTTPS. Any deployment fronted by HTTPS (reverse
    proxy / cloud surface) should set AIO_COOKIE_SECURE=1 so the cookie
    is only ever transmitted over TLS.
    """
    raw = os.environ.get("AIO_COOKIE_SECURE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def set_local_session_cookie(response: Response) -> None:
    """Issue an HttpOnly same-origin browser session for the local API."""
    response.set_cookie(
        LOCAL_SESSION_COOKIE,
        get_local_token(),
        httponly=True,
        secure=_cookie_secure_flag(),
        samesite="strict",
        path="/",
    )


async def require_local_auth(
    x_local_token: Optional[str] = Header(None, alias="X-Local-Token"),
    authorization: Optional[str] = Header(None),
    local_session: Optional[str] = Cookie(None, alias=LOCAL_SESSION_COOKIE),
) -> None:
    """FastAPI dependency: require local token header, bearer token, or session cookie."""
    if x_local_token:
        _validate_token(x_local_token)
        return
    token = _bearer_token(authorization)
    if token:
        _validate_token(token)
        return
    if local_session:
        _validate_token(local_session)
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_local_auth_or_localhost(
    request: Request,
    x_local_token: Optional[str] = Header(None, alias="X-Local-Token"),
    authorization: Optional[str] = Header(None),
    local_session: Optional[str] = Cookie(None, alias=LOCAL_SESSION_COOKIE),
) -> None:
    """FastAPI dependency for session-bootstrap endpoints.

    Accepts the local token (Electron / CLI) OR a direct loopback connection
    from 127.0.0.1 / ::1.  This lets the browser open the app without needing
    to carry a secret — the server only binds to localhost anyway.
    """
    if _is_valid_token(x_local_token):
        return
    token = _bearer_token(authorization)
    if _is_valid_token(token):
        return
    if _is_valid_token(local_session):
        return
    host = (request.client.host if request.client else "") or ""
    if host in ("127.0.0.1", "::1", "localhost"):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
