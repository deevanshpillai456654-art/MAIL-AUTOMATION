"""
OAuth router — manage OAuth tokens and provider flows.
Prefix: /oauth

Token values (access_token, refresh_token) are NEVER returned in API responses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from .models import (
    APIResponse,
    OAuthTokenCreateRequest,
    OAuthTokenSafe,
)
from ..shared.constants import OAUTH_PROVIDERS
from ..shared.utils import (
    decrypt_secret,
    encrypt_secret,
    generate_token_id,
    utc_now_str,
)

router = APIRouter(prefix="/oauth", tags=["oauth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_safe_token(row: dict[str, Any]) -> OAuthTokenSafe:
    scopes_raw = row.get("scopes", "[]")
    if isinstance(scopes_raw, str):
        try:
            scopes = json.loads(scopes_raw)
        except Exception:
            scopes = []
    else:
        scopes = scopes_raw

    return OAuthTokenSafe(
        token_id=row["id"],
        connector_id=row["connector_id"],
        tenant_id=row["tenant_id"],
        provider=row["provider"],
        expires_at=datetime.fromisoformat(row["expires_at"]) if row.get("expires_at") else None,
        scopes=scopes,
        created_at=datetime.fromisoformat(row["created_at"]),
        is_valid=bool(row.get("is_valid", 1)),
    )


def _require_token(token_id: str, tenant_id: Optional[str] = None) -> dict[str, Any]:
    db = get_panel_db()
    if tenant_id:
        row = db.fetch_one(
            "SELECT * FROM oauth_tokens WHERE id = ? AND tenant_id = ?",
            (token_id, tenant_id),
        )
    else:
        row = db.fetch_one("SELECT * FROM oauth_tokens WHERE id = ?", (token_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Token '{token_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/providers", summary="List supported OAuth providers")
async def list_providers():
    """Return provider metadata without any secrets."""
    safe_providers: dict[str, Any] = {}
    for pid, pdata in OAUTH_PROVIDERS.items():
        safe_providers[pid] = {
            "provider_id": pid,
            "display_name": pdata["display_name"],
            "required_config": pdata["required_config"],
            "supports_refresh": pdata["supports_refresh"],
            "icon": pdata.get("icon"),
            "auth_url_template": pdata["auth_url"],
            "scopes": pdata.get("scopes", []),
        }
    return safe_providers


@router.get("/tokens", response_model=list[OAuthTokenSafe], summary="List OAuth tokens for tenant")
async def list_tokens(
    tenant_id: str = Query(...),
    provider: Optional[str] = Query(None),
    connector_id: Optional[str] = Query(None),
):
    db = get_panel_db()
    sql = "SELECT * FROM oauth_tokens WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if provider:
        sql += " AND provider = ?"
        params.append(provider)
    if connector_id:
        sql += " AND connector_id = ?"
        params.append(connector_id)
    sql += " ORDER BY created_at DESC"
    rows = db.fetch_all(sql, params)
    return [_row_to_safe_token(r) for r in rows]


@router.post(
    "/tokens",
    response_model=OAuthTokenSafe,
    status_code=status.HTTP_201_CREATED,
    summary="Store new OAuth token (encrypted)",
)
async def create_token(body: OAuthTokenCreateRequest, tenant_id: str = Query(...)):
    db = get_panel_db()
    token_id = generate_token_id()
    now = utc_now_str()

    access_enc = encrypt_secret(body.access_token)
    refresh_enc = encrypt_secret(body.refresh_token) if body.refresh_token else None

    db.execute(
        """
        INSERT INTO oauth_tokens
            (id, connector_id, tenant_id, provider, access_token_enc,
             refresh_token_enc, expires_at, scopes, created_at, is_valid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(connector_id, tenant_id, provider) DO UPDATE SET
            access_token_enc=excluded.access_token_enc,
            refresh_token_enc=excluded.refresh_token_enc,
            expires_at=excluded.expires_at,
            scopes=excluded.scopes,
            is_valid=1
        """,
        (
            token_id,
            body.connector_id,
            tenant_id,
            body.provider,
            access_enc,
            refresh_enc,
            body.expires_at.isoformat() if body.expires_at else None,
            json.dumps(body.scopes),
            now,
        ),
    )
    # Re-fetch the actual stored row (id may differ on conflict update)
    actual_row = db.fetch_one(
        "SELECT * FROM oauth_tokens WHERE connector_id=? AND tenant_id=? AND provider=?",
        (body.connector_id, tenant_id, body.provider),
    )

    return _row_to_safe_token(actual_row)


@router.delete("/tokens/{token_id}", response_model=APIResponse, summary="Revoke OAuth token")
async def revoke_token(token_id: str, tenant_id: str = Query(...)):
    _require_token(token_id, tenant_id)
    db = get_panel_db()
    db.execute(
        "UPDATE oauth_tokens SET is_valid = 0 WHERE id = ? AND tenant_id = ?",
        (token_id, tenant_id),
    )
    return APIResponse(message=f"Token '{token_id}' revoked")


@router.get("/tokens/{token_id}/status", summary="Check token validity")
async def check_token_status(token_id: str, tenant_id: str = Query(...)):
    row = _require_token(token_id, tenant_id)
    is_valid = bool(row.get("is_valid", 1))

    # Check expiry
    expires_at_str = row.get("expires_at")
    expired = False
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            expired = expires_at < datetime.now(tz=timezone.utc)
            if expired:
                is_valid = False
        except Exception:
            pass

    return {
        "token_id": token_id,
        "is_valid": is_valid,
        "expired": expired,
        "expires_at": expires_at_str,
        "provider": row["provider"],
    }


@router.post("/tokens/{token_id}/refresh", response_model=OAuthTokenSafe, summary="Refresh OAuth token")
async def refresh_token(token_id: str, tenant_id: str = Query(...)):
    row = _require_token(token_id, tenant_id)
    provider_id = row["provider"]
    provider = OAUTH_PROVIDERS.get(provider_id)

    if not provider:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider '{provider_id}'",
        )

    if not provider.get("supports_refresh"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Provider '{provider_id}' does not support token refresh",
        )

    # Decrypt the refresh token
    refresh_enc = row.get("refresh_token_enc")
    if not refresh_enc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No refresh token stored for this token",
        )

    try:
        refresh_token_val = decrypt_secret(refresh_enc)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to decrypt refresh token: {exc}",
        )

    # Read client credentials from environment using the provider's env-var prefix
    import os
    provider_env = provider_id.upper()
    client_id = os.environ.get(f"{provider_env}_CLIENT_ID", "")
    client_secret = os.environ.get(f"{provider_env}_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OAuth client credentials not configured for provider '{provider_id}'. "
                   f"Set {provider_env}_CLIENT_ID and {provider_env}_CLIENT_SECRET.",
        )

    # Perform the actual token refresh
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                provider["token_url"],
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token_val,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            token_data = response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Token refresh failed: {exc}",
        )

    new_access = token_data.get("access_token", "")
    new_refresh = token_data.get("refresh_token", refresh_token_val)
    expires_in = token_data.get("expires_in")

    new_access_enc = encrypt_secret(new_access)
    new_refresh_enc = encrypt_secret(new_refresh)

    now = utc_now_str()
    new_expires: Optional[str] = None
    if expires_in:
        from datetime import timedelta
        new_expires = (datetime.now(tz=timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()

    db = get_panel_db()
    db.execute(
        """
        UPDATE oauth_tokens
        SET access_token_enc = ?, refresh_token_enc = ?,
            expires_at = ?, is_valid = 1
        WHERE id = ?
        """,
        (new_access_enc, new_refresh_enc, new_expires, token_id),
    )

    row = _require_token(token_id)
    return _row_to_safe_token(row)


@router.get("/authorize/{provider}", summary="Start OAuth authorization flow")
async def authorize(
    provider: str,
    tenant_id: str = Query(...),
    connector_id: str = Query(...),
    redirect_uri: str = Query(...),
    shop: Optional[str] = Query(None, description="Required for Shopify"),
):
    provider_config = OAUTH_PROVIDERS.get(provider)
    if not provider_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider}' not supported",
        )

    # Validate redirect_uri to prevent open redirect abuse
    from urllib.parse import urlparse as _urlparse
    _parsed_redir = _urlparse(redirect_uri)
    if _parsed_redir.scheme not in ("https", "http") or not _parsed_redir.netloc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="redirect_uri must be an absolute http/https URL",
        )

    import os
    client_id = os.environ.get(f"{provider.upper()}_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"OAuth client_id not configured for provider '{provider}'. Set {provider.upper()}_CLIENT_ID.",
        )

    # Build auth URL
    base_url = provider_config["auth_url"]
    if "{shop}" in base_url:
        if not shop:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="shop parameter is required for Shopify",
            )
        base_url = base_url.replace("{shop}", shop)

    import secrets as _secrets
    scopes = " ".join(provider_config.get("scopes", []))
    state = _secrets.token_urlsafe(24)

    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "state": state,
    }

    auth_url = f"{base_url}?{urlencode(params)}"
    return {"auth_url": auth_url, "provider": provider, "state": state}
