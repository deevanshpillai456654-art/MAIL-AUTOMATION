"""Clean OAuth router — /api/v1/oauth/* endpoints only.

Provides:
  POST/GET /oauth/google/start
  GET/POST  /oauth/google/callback
  POST/GET  /oauth/microsoft/start
  GET/POST  /oauth/microsoft/callback
  POST/GET  /oauth/yahoo/start
  GET/POST  /oauth/yahoo/callback

Mount under /api/v1 in main.py.
"""
from __future__ import annotations

import json
import logging
from html import escape
from time import time
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from backend import config
from backend.auth.middleware import require_local_request
from backend.auth.providers.google import GoogleOAuthProvider
from backend.auth.providers.microsoft import MicrosoftOAuthProvider
from backend.auth.providers.yahoo import YahooOAuthProvider
from backend.auth.state_store import OAuthStateStore
from backend.auth.token_store import TokenStore
from backend.core.account_persistence import account_metadata
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.db.database import Database

router = APIRouter()
logger = logging.getLogger(__name__)

_db: Optional[Database] = None


def _get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(config.DB_PATH)
    return _db


class OAuthStartBody(BaseModel):
    redirect_after: Optional[str] = Field(default="/dashboard", max_length=500)
    email: Optional[str] = Field(default=None, max_length=300)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v):
        if v is None:
            return None
        v = v.strip().lower()
        return v or None


def _base_url(request: Request) -> str:
    host = request.url.hostname or "127.0.0.1"
    if host not in ("127.0.0.1", "localhost"):
        host = "127.0.0.1"
    port = f":{request.url.port}" if request.url.port else f":{config.API_PORT}"
    return f"http://127.0.0.1{port}"


def _callback_url(request: Request, provider_slug: str) -> str:
    # Honour explicit redirect URI from config (populated from .env / settings)
    # so the registered OAuth app URI wins over the server's own port.
    configured = {
        "google": config.GMAIL_REDIRECT_URI,
        "microsoft": config.OUTLOOK_REDIRECT_URI,
    }.get(provider_slug, "")
    default = f"http://127.0.0.1:{config.API_PORT}/api/v1/oauth/{provider_slug}/callback"
    if configured and configured != default and "YOUR_" not in configured:
        return configured
    port = f":{request.url.port}" if request.url.port else f":{config.API_PORT}"
    return f"http://127.0.0.1{port}/api/v1/oauth/{provider_slug}/callback"


def _result_page(provider: str, status: str, message: str, email: str = None) -> HTMLResponse:
    safe_provider = escape(provider)
    safe_status = escape(status)
    safe_message = escape(message)
    safe_email = escape(email or "")
    query = f"oauth={quote(status)}&provider={quote(provider)}"
    if email:
        query += f"&email={quote(email)}"
    html = (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f'<title>AI Email Organizer OAuth</title></head><body>'
        f'<main style="font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:12vh auto;padding:24px">'
        f'<h1>{safe_provider.title()} connection {safe_status}</h1>'
        f'<p>{safe_message}</p><p>{safe_email}</p>'
        f'<a href="/dashboard?{query}">Return to dashboard</a></main>'
        f'<script>setTimeout(()=>{{window.location.href="/dashboard?{query}";}},1200);</script>'
        f'</body></html>'
    )
    return HTMLResponse(html)


def _profile_email(provider: str, profile: dict) -> str:
    for key in ("email", "mail", "userPrincipalName", "login", "primaryEmail"):
        v = profile.get(key)
        if v:
            return str(v).lower()
    return f"{provider}_{int(time())}@local.invalid"


def _store_account(provider: str, oauth_group: str, email: str,
                   tokens: dict, profile: dict) -> int:
    db = _get_db()
    capability = ProviderCapabilityRegistry().get(provider)
    metadata = account_metadata(
        20,
        auth_type="oauth",
        oauth_provider=oauth_group,
        profile=profile,
        token_scopes=tokens.get("scope") or sorted(capability.protocols),
        sync_status="pending",
        password_required=False,
        app_password_required=False,
        validate_oauth_tokens_only=True,
    )
    account_id = db.upsert_account(
        provider=provider,
        email=email,
        status="connected",
        reconnect_state="ok",
        metadata=metadata,
        auth_type="oauth",
        oauth_provider=oauth_group,
        token_scopes=json.dumps(tokens.get("scope") or sorted(capability.protocols)),
        sync_status="pending",
        webhook_enabled=1 if capability.supports_watch else 0,
        provider_capabilities=json.dumps(capability.as_dict(), sort_keys=True),
    )
    db.add_provider_diagnostic(account_id, provider, "oauth_connected",
                               {"ok": True, "password_required": False, "sync_status": "pending"})
    db.add_sync_status(account_id, "pending")
    TokenStore(db).save(
        account_id,
        tokens["access_token"],
        tokens.get("refresh_token"),
        tokens.get("expires_in"),
    )
    return account_id


# ── Google ───────────────────────────────────────────────────────────────────

@router.post("/oauth/google/start")
async def google_start(request: Request, body: OAuthStartBody = None):
    cb = _callback_url(request, "google")
    prov = GoogleOAuthProvider(db=_get_db(), redirect_uri=cb)
    result = prov.create_authorization_request(redirect_uri=cb,
                                               login_hint=body.email if body else None)
    if not result.get("configured"):
        result.update({"status": "provider_setup_required", "setup_required": True,
                       "setup_url": "/setup#provider-setup"})
    return JSONResponse(result, status_code=200 if result.get("configured") else 428)


@router.get("/oauth/google/start")
async def google_start_redirect(request: Request, email: str = None):
    resp = await google_start(request, OAuthStartBody(email=email) if email else None)
    data = json.loads(resp.body.decode())
    if resp.status_code >= 400:
        from backend.auth.provider_config import OAUTH_GROUPS, ProviderConfigManager
        from backend.api.routes import oauth_setup_page
        status = ProviderConfigManager().status("gmail", _base_url(request))
        return oauth_setup_page("gmail", status, _base_url(request), email or "")
    return RedirectResponse(data["auth_url"])


@router.get("/oauth/google/callback")
async def google_callback(request: Request, code: str = None,
                          state: str = None, error: str = None):
    require_local_request(request)
    if error:
        return _result_page("gmail", "failed", f"Google OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="OAuth code and state required")
    db = _get_db()
    state_row = OAuthStateStore(db).consume("gmail", state)
    if not state_row:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    prov = GoogleOAuthProvider(db=db, redirect_uri=state_row["redirect_uri"])
    tokens = prov.exchange_code(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_profile(tokens["access_token"]) or {}
    email = _profile_email("gmail", profile)
    _store_account("gmail", "gmail", email, tokens, profile)
    return _result_page("gmail", "success", "Gmail account connected.", email)


@router.post("/oauth/google/callback")
async def google_callback_post(request: Request):
    payload = await request.json()
    return await google_callback(request, code=payload.get("code"),
                                 state=payload.get("state"), error=payload.get("error"))


# ── Microsoft ─────────────────────────────────────────────────────────────────

@router.post("/oauth/microsoft/start")
async def microsoft_start(request: Request, body: OAuthStartBody = None):
    cb = _callback_url(request, "microsoft")
    prov = MicrosoftOAuthProvider(db=_get_db(), redirect_uri=cb)
    result = prov.create_authorization_request(redirect_uri=cb,
                                               login_hint=body.email if body else None)
    if not result.get("configured"):
        result.update({"status": "provider_setup_required", "setup_required": True,
                       "setup_url": "/setup#provider-setup"})
    return JSONResponse(result, status_code=200 if result.get("configured") else 428)


@router.get("/oauth/microsoft/start")
async def microsoft_start_redirect(request: Request, email: str = None):
    resp = await microsoft_start(request, OAuthStartBody(email=email) if email else None)
    data = json.loads(resp.body.decode())
    if resp.status_code >= 400:
        from backend.auth.provider_config import ProviderConfigManager
        from backend.api.routes import oauth_setup_page
        status = ProviderConfigManager().status("microsoft", _base_url(request))
        return oauth_setup_page("microsoft", status, _base_url(request), email or "")
    return RedirectResponse(data["auth_url"])


@router.get("/oauth/microsoft/callback")
async def microsoft_callback(request: Request, code: str = None,
                              state: str = None, error: str = None):
    require_local_request(request)
    if error:
        return _result_page("outlook", "failed", f"Microsoft OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="OAuth code and state required")
    db = _get_db()
    state_row = OAuthStateStore(db).consume("outlook", state)
    if not state_row:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    prov = MicrosoftOAuthProvider(db=db, redirect_uri=state_row["redirect_uri"])
    tokens = prov.exchange_code(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_profile(tokens["access_token"]) or {}
    email = _profile_email("outlook", profile)
    _store_account("outlook", "microsoft", email, tokens, profile)
    return _result_page("outlook", "success", "Outlook account connected.", email)


@router.post("/oauth/microsoft/callback")
async def microsoft_callback_post(request: Request):
    payload = await request.json()
    return await microsoft_callback(request, code=payload.get("code"),
                                    state=payload.get("state"), error=payload.get("error"))


# ── Yahoo ─────────────────────────────────────────────────────────────────────

@router.post("/oauth/yahoo/start")
async def yahoo_start(request: Request, body: OAuthStartBody = None):
    cb = _callback_url(request, "yahoo")
    prov = YahooOAuthProvider(db=_get_db(), redirect_uri=cb)
    result = prov.create_authorization_request(redirect_uri=cb,
                                               login_hint=body.email if body else None)
    if not result.get("configured"):
        result.update({"status": "provider_setup_required", "setup_required": True,
                       "setup_url": "/setup#provider-setup"})
    return JSONResponse(result, status_code=200 if result.get("configured") else 428)


@router.get("/oauth/yahoo/start")
async def yahoo_start_redirect(request: Request, email: str = None):
    resp = await yahoo_start(request, OAuthStartBody(email=email) if email else None)
    data = json.loads(resp.body.decode())
    if resp.status_code >= 400:
        from backend.auth.provider_config import ProviderConfigManager
        from backend.api.routes import oauth_setup_page
        status = ProviderConfigManager().status("yahoo", _base_url(request))
        return oauth_setup_page("yahoo", status, _base_url(request), email or "")
    return RedirectResponse(data["auth_url"])


@router.get("/oauth/yahoo/callback")
async def yahoo_callback(request: Request, code: str = None,
                         state: str = None, error: str = None):
    require_local_request(request)
    if error:
        return _result_page("yahoo", "failed", f"Yahoo OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="OAuth code and state required")
    db = _get_db()
    state_row = OAuthStateStore(db).consume("yahoo", state)
    if not state_row:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    prov = YahooOAuthProvider(db=db, redirect_uri=state_row["redirect_uri"])
    tokens = prov.exchange_code(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_profile(tokens["access_token"]) or {}
    email = _profile_email("yahoo", profile)
    _store_account("yahoo", "yahoo", email, tokens, profile)
    return _result_page("yahoo", "success", "Yahoo account connected.", email)


@router.post("/oauth/yahoo/callback")
async def yahoo_callback_post(request: Request):
    payload = await request.json()
    return await yahoo_callback(request, code=payload.get("code"),
                                state=payload.get("state"), error=payload.get("error"))


# ── Zoho ──────────────────────────────────────────────────────────────────────

def _universal_start(provider: str, request: Request, email: str = None):
    from backend.auth.universal_oauth import UniversalOAuth
    cb = _callback_url(request, provider)
    try:
        prov = UniversalOAuth(provider, db=_get_db(), redirect_uri=cb)
    except ValueError:
        return JSONResponse({"configured": False, "provider": provider,
                             "message": f"{provider.title()} is not supported as an OAuth provider.",
                             "status": "provider_setup_required", "setup_required": True,
                             "setup_url": "/setup#provider-setup"}, status_code=428)
    result = prov.create_authorization_request(redirect_uri=cb, login_hint=email)
    if not result.get("configured"):
        result.update({"status": "provider_setup_required", "setup_required": True,
                       "setup_url": "/setup#provider-setup"})
    return JSONResponse(result, status_code=200 if result.get("configured") else 428)


def _universal_callback(provider: str, request: Request,
                        code: str = None, state: str = None, error: str = None):
    from backend.auth.universal_oauth import UniversalOAuth
    require_local_request(request)
    if error:
        return _result_page(provider, "failed", f"{provider.title()} OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="OAuth code and state required")
    db = _get_db()
    state_row = OAuthStateStore(db).consume(provider, state)
    if not state_row:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    prov = UniversalOAuth(provider, db=db, redirect_uri=state_row["redirect_uri"])
    tokens = prov.exchange_code_for_tokens(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_user_profile(tokens["access_token"]) or {}
    email = _profile_email(provider, profile)
    _store_account(provider, provider, email, tokens, profile)
    return _result_page(provider, "success", f"{provider.title()} account connected.", email)


@router.post("/oauth/zoho/start")
async def zoho_start(request: Request, body: OAuthStartBody = None):
    return _universal_start("zoho", request, body.email if body else None)


@router.get("/oauth/zoho/start")
async def zoho_start_redirect(request: Request, email: str = None):
    resp = _universal_start("zoho", request, email)
    data = json.loads(resp.body.decode())
    if resp.status_code >= 400:
        from backend.auth.provider_config import ProviderConfigManager
        from backend.api.routes import oauth_setup_page
        return oauth_setup_page("zoho", ProviderConfigManager().status("zoho", _base_url(request)),
                                _base_url(request), email or "")
    return RedirectResponse(data["auth_url"])


@router.get("/oauth/zoho/callback")
async def zoho_callback(request: Request, code: str = None,
                        state: str = None, error: str = None):
    return _universal_callback("zoho", request, code=code, state=state, error=error)


@router.post("/oauth/zoho/callback")
async def zoho_callback_post(request: Request):
    payload = await request.json()
    return _universal_callback("zoho", request, code=payload.get("code"),
                               state=payload.get("state"), error=payload.get("error"))


# ── Yandex ────────────────────────────────────────────────────────────────────

@router.post("/oauth/yandex/start")
async def yandex_start(request: Request, body: OAuthStartBody = None):
    return _universal_start("yandex", request, body.email if body else None)


@router.get("/oauth/yandex/start")
async def yandex_start_redirect(request: Request, email: str = None):
    resp = _universal_start("yandex", request, email)
    data = json.loads(resp.body.decode())
    if resp.status_code >= 400:
        from backend.auth.provider_config import ProviderConfigManager
        from backend.api.routes import oauth_setup_page
        return oauth_setup_page("yandex", ProviderConfigManager().status("yandex", _base_url(request)),
                                _base_url(request), email or "")
    return RedirectResponse(data["auth_url"])


@router.get("/oauth/yandex/callback")
async def yandex_callback(request: Request, code: str = None,
                          state: str = None, error: str = None):
    return _universal_callback("yandex", request, code=code, state=state, error=error)


@router.post("/oauth/yandex/callback")
async def yandex_callback_post(request: Request):
    payload = await request.json()
    return _universal_callback("yandex", request, code=payload.get("code"),
                               state=payload.get("state"), error=payload.get("error"))
