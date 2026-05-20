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
from backend.auth.provider_config import OAUTH_GROUPS, ProviderConfigManager, normalize_email_address, oauth_group_for
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
    provider: Optional[str] = Field(default=None, max_length=80)
    redirect_after: Optional[str] = Field(default="/dashboard", max_length=500)
    email: Optional[str] = Field(default=None, max_length=300)
    email_address: Optional[str] = Field(default=None, max_length=300)

    @field_validator("email", "email_address")
    @classmethod
    def normalize_email(cls, v):
        if v is None:
            return None
        v = v.strip().lower()
        return v or None


class OAuthConfigBody(BaseModel):
    provider: str = Field(..., max_length=80)
    email_address: str = Field(..., max_length=300)
    client_id: str = Field(..., max_length=500)
    client_secret: str = Field(..., max_length=1000)
    redirect_uri: Optional[str] = Field(default=None, max_length=500)
    tenant_id: Optional[str] = Field(default="common", max_length=200)
    provider_options: dict = Field(default_factory=dict)

    @field_validator("email_address")
    @classmethod
    def normalize_email(cls, v):
        v = (v or "").strip().lower()
        if "@" not in v:
            raise ValueError("Valid email is required")
        return v


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


def _requested_email(body: OAuthStartBody = None, email: str = None) -> str:
    raw = email or (body.email_address if body else None) or (body.email if body else None)
    value = normalize_email_address(raw)
    if not value or "@" not in value:
        raise HTTPException(
            status_code=400,
            detail={"status": "email_required", "message": "Enter the email address before configuring or starting OAuth."},
        )
    return value


def _oauth_group(provider: str) -> str:
    key = (provider or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key == "google":
        key = "gmail"
    group = oauth_group_for(key) or key
    if group not in OAUTH_GROUPS:
        raise HTTPException(status_code=400, detail={"status": "unsupported_provider", "message": f"{provider} is not an OAuth-capable email provider."})
    return group


def _callback_slug_for_group(group: str) -> str:
    return {"gmail": "google", "microsoft": "microsoft", "yahoo": "yahoo", "zoho": "zoho", "yandex": "yandex"}.get(group, group)


def _start_path_for_group(group: str) -> str:
    return {
        "gmail": "/api/v1/oauth/google/start",
        "microsoft": "/api/v1/oauth/microsoft/start",
        "yahoo": "/api/v1/oauth/yahoo/start",
        "zoho": "/api/v1/oauth/zoho/start",
        "yandex": "/api/v1/oauth/yandex/start",
    }[group]


def _oauth_public_config(status: dict) -> dict:
    return {
        "provider": status.get("provider"),
        "email_address": status.get("email_address"),
        "client_id": status.get("client_id") or "",
        "client_secret": status.get("client_secret") or "",
        "client_secret_masked": bool(status.get("client_secret_masked")),
        "redirect_uri": status.get("redirect_uri"),
        "provider_options": status.get("provider_options") or {},
        "config_scope": status.get("config_scope"),
        "is_shared": bool(status.get("is_shared")),
        "configured": bool(status.get("configured")),
        "source": status.get("source"),
        "tenant_id": status.get("tenant_id"),
    }


def _config_for_oauth_start(group: str, email: str, request: Request) -> dict:
    slug = _callback_slug_for_group(group)
    cb = _callback_url(request, slug)
    cfg = ProviderConfigManager().get_oauth_config(group, runtime_redirect_uri=cb, email_address=email)
    if not cfg.get("configured"):
        raise HTTPException(
            status_code=428,
            detail={
                "status": "provider_setup_required",
                "message": "No OAuth configuration found for this provider/email. Please configure OAuth app details first.",
                "provider": group,
                "email_address": email,
                "setup_required": True,
                "setup_url": "/dashboard#accounts-oauth-setup",
                "start_path": _start_path_for_group(group),
            },
        )
    return cfg


def _attach_start_config(result: dict, cfg: dict, email: str) -> dict:
    result.update({
        "email_address": email,
        "oauth_config_provider": cfg.get("oauth_config_provider"),
        "oauth_config_email": cfg.get("oauth_config_email"),
        "config_scope": cfg.get("config_scope"),
    })
    return result


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
    for key in ("email", "mail", "userPrincipalName", "login", "primaryEmail", "default_email"):
        v = profile.get(key)
        if v:
            return str(v).lower()
    return f"{provider}_{int(time())}@local.invalid"


def _email_mismatch_response(provider: str, state_row: dict, profile_email: str) -> Optional[HTMLResponse]:
    requested = (state_row.get("requested_email") or "").strip().lower()
    actual = (profile_email or "").strip().lower()
    if not requested or requested == actual:
        return None
    logger.warning(
        "%s OAuth returned %s but the requested account was %s; refusing to overwrite tokens",
        provider,
        actual,
        requested,
    )
    return _result_page(
        provider,
        "failed",
        f"Wrong account selected. Expected {requested} but received {actual}. Please retry and select the correct account.",
        actual,
    )


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
    try:
        from backend.core.mailbox_taxonomy import ProviderMailboxTaxonomy
        ProviderMailboxTaxonomy(db).sync_mailbox_structure(account_id)
    except Exception as exc:
        logger.debug("Folder/label discovery did not complete after OAuth for %s: %s", account_id, exc)
    return account_id


@router.post("/oauth/config")
async def save_oauth_config(request: Request, payload: OAuthConfigBody):
    require_local_request(request)
    group = _oauth_group(payload.provider)
    try:
        status = ProviderConfigManager().save_oauth_config(
            provider=group,
            email_address=payload.email_address,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            redirect_uri=payload.redirect_uri,
            tenant_id=payload.tenant_id,
            provider_options=payload.provider_options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"status": "invalid_provider_config", "message": str(exc)})
    return {"status": "saved", **_oauth_public_config(status)}


@router.get("/oauth/config")
async def get_oauth_config(request: Request, provider: str, email_address: str):
    require_local_request(request)
    email = _requested_email(email=email_address)
    group = _oauth_group(provider)
    status = ProviderConfigManager().status(group, _base_url(request), email_address=email)
    if not status.get("configured"):
        return JSONResponse(
            {
                "status": "provider_setup_required",
                "message": "No OAuth configuration found for this provider/email. Please configure OAuth app details first.",
                **_oauth_public_config(status),
            },
            status_code=404,
        )
    return {"status": "ready", **_oauth_public_config(status)}


@router.post("/oauth/start")
async def oauth_start(request: Request, body: OAuthStartBody):
    group = _oauth_group(body.provider)
    email = _requested_email(body)
    resp = await _start_response_for_group(group, request, email=email, redirect_after=body.redirect_after)
    return resp


@router.get("/oauth/start")
async def oauth_start_redirect(request: Request, provider: str, email_address: str = None, email: str = None):
    group = _oauth_group(provider)
    requested = _requested_email(email=email_address or email)
    resp = await _start_response_for_group(group, request, email=requested)
    data = json.loads(resp.body.decode())
    return RedirectResponse(data["auth_url"])


async def _start_response_for_group(group: str, request: Request, email: str, redirect_after: str = "/dashboard") -> JSONResponse:
    if group == "gmail":
        return await google_start(request, OAuthStartBody(email_address=email, redirect_after=redirect_after))
    if group == "microsoft":
        return await microsoft_start(request, OAuthStartBody(email_address=email, redirect_after=redirect_after))
    if group == "yahoo":
        return await yahoo_start(request, OAuthStartBody(email_address=email, redirect_after=redirect_after))
    if group == "zoho":
        return await zoho_start(request, OAuthStartBody(email_address=email, redirect_after=redirect_after))
    if group == "yandex":
        return await yandex_start(request, OAuthStartBody(email_address=email, redirect_after=redirect_after))
    raise HTTPException(status_code=400, detail={"status": "unsupported_provider", "message": f"{group} is not supported."})


# ── Google ───────────────────────────────────────────────────────────────────

@router.post("/oauth/google/start")
async def google_start(request: Request, body: OAuthStartBody = None):
    email = _requested_email(body)
    cfg = _config_for_oauth_start("gmail", email, request)
    prov = GoogleOAuthProvider(
        db=_get_db(),
        redirect_uri=cfg["redirect_uri"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        email_address=cfg.get("oauth_config_email"),
    )
    result = prov.create_authorization_request(
        redirect_uri=cfg["redirect_uri"],
        login_hint=email,
        oauth_config_provider=cfg.get("oauth_config_provider"),
        oauth_config_email=cfg.get("oauth_config_email"),
        redirect_after_callback=body.redirect_after if body else "/dashboard",
    )
    return JSONResponse(_attach_start_config(result, cfg, email))


@router.get("/oauth/google/start")
async def google_start_redirect(request: Request, email: str = None):
    requested = _requested_email(email=email)
    try:
        resp = await google_start(request, OAuthStartBody(email_address=requested))
    except HTTPException as exc:
        if exc.status_code == 428:
            from backend.api.routes import oauth_setup_page
            status = ProviderConfigManager().status("gmail", _base_url(request), email_address=requested)
            return oauth_setup_page("gmail", status, _base_url(request), requested)
        raise
    data = json.loads(resp.body.decode())
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
    prov = GoogleOAuthProvider(db=db, redirect_uri=state_row["redirect_uri"], email_address=state_row.get("oauth_config_email"))
    tokens = prov.exchange_code(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_profile(tokens["access_token"]) or {}
    email = _profile_email("gmail", profile)
    mismatch = _email_mismatch_response("gmail", state_row, email)
    if mismatch:
        return mismatch
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
    email = _requested_email(body)
    cfg = _config_for_oauth_start("microsoft", email, request)
    prov = MicrosoftOAuthProvider(
        db=_get_db(),
        redirect_uri=cfg["redirect_uri"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        tenant_id=cfg.get("tenant_id") or "common",
        email_address=cfg.get("oauth_config_email"),
    )
    result = prov.create_authorization_request(
        redirect_uri=cfg["redirect_uri"],
        login_hint=email,
        oauth_config_provider=cfg.get("oauth_config_provider"),
        oauth_config_email=cfg.get("oauth_config_email"),
        redirect_after_callback=body.redirect_after if body else "/dashboard",
    )
    return JSONResponse(_attach_start_config(result, cfg, email))


@router.get("/oauth/microsoft/start")
async def microsoft_start_redirect(request: Request, email: str = None):
    requested = _requested_email(email=email)
    try:
        resp = await microsoft_start(request, OAuthStartBody(email_address=requested))
    except HTTPException as exc:
        if exc.status_code == 428:
            from backend.api.routes import oauth_setup_page
            status = ProviderConfigManager().status("microsoft", _base_url(request), email_address=requested)
            return oauth_setup_page("microsoft", status, _base_url(request), requested)
        raise
    data = json.loads(resp.body.decode())
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
    prov = MicrosoftOAuthProvider(db=db, redirect_uri=state_row["redirect_uri"], email_address=state_row.get("oauth_config_email"))
    tokens = prov.exchange_code(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_profile(tokens["access_token"]) or {}
    email = _profile_email("outlook", profile)
    mismatch = _email_mismatch_response("outlook", state_row, email)
    if mismatch:
        return mismatch
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
    email = _requested_email(body)
    cfg = _config_for_oauth_start("yahoo", email, request)
    prov = YahooOAuthProvider(
        db=_get_db(),
        redirect_uri=cfg["redirect_uri"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        email_address=cfg.get("oauth_config_email"),
    )
    result = prov.create_authorization_request(
        redirect_uri=cfg["redirect_uri"],
        login_hint=email,
        oauth_config_provider=cfg.get("oauth_config_provider"),
        oauth_config_email=cfg.get("oauth_config_email"),
        redirect_after_callback=body.redirect_after if body else "/dashboard",
    )
    return JSONResponse(_attach_start_config(result, cfg, email))


@router.get("/oauth/yahoo/start")
async def yahoo_start_redirect(request: Request, email: str = None):
    requested = _requested_email(email=email)
    try:
        resp = await yahoo_start(request, OAuthStartBody(email_address=requested))
    except HTTPException as exc:
        if exc.status_code == 428:
            from backend.api.routes import oauth_setup_page
            status = ProviderConfigManager().status("yahoo", _base_url(request), email_address=requested)
            return oauth_setup_page("yahoo", status, _base_url(request), requested)
        raise
    data = json.loads(resp.body.decode())
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
    prov = YahooOAuthProvider(db=db, redirect_uri=state_row["redirect_uri"], email_address=state_row.get("oauth_config_email"))
    tokens = prov.exchange_code(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_profile(tokens["access_token"]) or {}
    email = _profile_email("yahoo", profile)
    mismatch = _email_mismatch_response("yahoo", state_row, email)
    if mismatch:
        return mismatch
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
    requested = _requested_email(email=email)
    cfg = _config_for_oauth_start(provider, requested, request)
    try:
        prov = UniversalOAuth(provider, db=_get_db(), redirect_uri=cfg["redirect_uri"], email_address=cfg.get("oauth_config_email") or requested)
    except ValueError:
        return JSONResponse({"configured": False, "provider": provider,
                             "message": f"{provider.title()} is not supported as an OAuth provider.",
                             "status": "provider_setup_required", "setup_required": True,
                             "setup_url": "/setup#provider-setup"}, status_code=428)
    result = prov.create_authorization_request(
        redirect_uri=cfg["redirect_uri"],
        login_hint=requested,
        oauth_config_provider=cfg.get("oauth_config_provider"),
        oauth_config_email=cfg.get("oauth_config_email"),
    )
    return JSONResponse(_attach_start_config(result, cfg, requested))


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
    prov = UniversalOAuth(provider, db=db, redirect_uri=state_row["redirect_uri"], email_address=state_row.get("oauth_config_email"))
    tokens = prov.exchange_code_for_tokens(code, state_row["redirect_uri"], state_row.get("code_verifier"))
    if not tokens:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    profile = prov.get_user_profile(tokens["access_token"]) or {}
    email = _profile_email(provider, profile)
    mismatch = _email_mismatch_response(provider, state_row, email)
    if mismatch:
        return mismatch
    _store_account(provider, provider, email, tokens, profile)
    return _result_page(provider, "success", f"{provider.title()} account connected.", email)


@router.post("/oauth/zoho/start")
async def zoho_start(request: Request, body: OAuthStartBody = None):
    return _universal_start("zoho", request, body.email if body else None)


@router.get("/oauth/zoho/start")
async def zoho_start_redirect(request: Request, email: str = None):
    requested = _requested_email(email=email)
    try:
        resp = _universal_start("zoho", request, requested)
    except HTTPException as exc:
        if exc.status_code != 428:
            raise
        from backend.auth.provider_config import ProviderConfigManager
        from backend.api.routes import oauth_setup_page
        return oauth_setup_page("zoho", ProviderConfigManager().status("zoho", _base_url(request), email_address=requested),
                                _base_url(request), requested)
    data = json.loads(resp.body.decode())
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
    requested = _requested_email(email=email)
    try:
        resp = _universal_start("yandex", request, requested)
    except HTTPException as exc:
        if exc.status_code != 428:
            raise
        from backend.auth.provider_config import ProviderConfigManager
        from backend.api.routes import oauth_setup_page
        return oauth_setup_page("yandex", ProviderConfigManager().status("yandex", _base_url(request), email_address=requested),
                                _base_url(request), requested)
    data = json.loads(resp.body.decode())
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
