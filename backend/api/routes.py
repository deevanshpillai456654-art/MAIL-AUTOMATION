import sys
import os
from pathlib import Path

# Add parent directory to path

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator, AliasChoices, ConfigDict
from typing import Optional, List, Dict, Union, Any
from datetime import datetime
from time import time
import asyncio
import json
import requests
import logging
from urllib.parse import quote
from html import escape

from backend.ai.classifier import EmailClassifier
from backend.db.database import Database
from backend.auth.local_auth import require_local_auth
from backend.auth.gmail_auth import GmailOAuth
from backend.auth.outlook_auth import OutlookOAuth
from backend.auth.universal_oauth import UniversalOAuth
from backend.auth.imap_auth import IMAPAccountManager
from backend.auth.token_crypto import TokenCipher
from backend.auth.provider_config import ProviderConfigManager, OAUTH_GROUPS, oauth_group_for
from backend.auth.universal_auth_engine import UniversalEmailAuthEngine
from backend.sync.gmail_sync import sync_gmail_account
from backend.sync.outlook_sync import sync_outlook_account
from backend.sync.imap_sync import sync_imap_account
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.core.account_persistence import detect_mail_settings, account_metadata
from backend.core.mailbox_orchestrator import MailboxOrchestrator
from backend.core.mailbox_health_monitor import MailboxHealthMonitor
from backend.core.mailbox_taxonomy import ProviderMailboxTaxonomy
from backend.core.attachment_storage import attachment_storage
from backend.core.scam_filter import FEEDBACK_CATEGORIES, normalize_feedback_category
from backend.ai.onnx_control_plane import get_onnx_control_plane
from backend.api.provider_detection import (
    PROVIDER_DOMAIN_RULES as _PROVIDER_DOMAIN_RULES,
    detect_mail_provider,
    domain_from_email as _domain_from_email,
    request_base_url,
)
from backend.scheduler.tasks import set_sync_interval, set_sync_enabled, get_sync_interval_seconds
from backend import config

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy initialization to avoid startup issues
_db = None
_classifier = None

VALID_CATEGORIES = [
    "Finance", "OTP", "Clients", "Personal", "Promotions", "Spam",
    "Newsletters", "Trading", "Logistics", "Purchases", "HR", "Support",
    "Bills", "Security", "Urgent", "Waiting Reply", "Scam", "Normal",
    "Marketing", "Sales", "Social Media", "Investor", "Leads",
]

def get_db() -> Database:
    global _db
    if _db is None:
        try:
            _db = Database(config.DB_PATH)
        except Exception as e:
            logger.error(f"Database initialization failed: {e}")
            raise
    return _db

def get_classifier() -> EmailClassifier:
    global _classifier
    if _classifier is None:
        try:
            _classifier = EmailClassifier(db=get_db())
        except Exception as e:
            logger.error(f"Classifier initialization failed: {e}")
            raise
    return _classifier


def _public_storage_attachment(meta) -> Dict[str, Any]:
    return {
        "id": meta.attachment_id,
        "attachment_id": meta.attachment_id,
        "filename": meta.filename,
        "content_type": meta.content_type,
        "size": meta.original_size or meta.size,
        "download_url": f"/api/v1/attachments/{quote(meta.attachment_id, safe='')}/download",
    }


def _public_payload_attachment(item: Any) -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        item = {"filename": item}
    if not isinstance(item, dict):
        return None
    attachment_id = item.get("attachment_id") or item.get("id")
    filename = item.get("filename") or item.get("name") or attachment_id or "attachment"
    download_url = item.get("download_url") or item.get("url") or item.get("href")
    if not download_url and attachment_id:
        download_url = f"/api/v1/attachments/{quote(str(attachment_id), safe='')}/download"
    public = {
        "id": attachment_id or filename,
        "attachment_id": attachment_id,
        "filename": filename,
        "content_type": item.get("content_type") or item.get("mime_type") or item.get("mimeType") or "application/octet-stream",
        "size": item.get("size") or item.get("size_bytes") or item.get("bytes") or 0,
        "download_url": download_url or "",
    }
    if item.get("data_url"):
        public["data_url"] = item["data_url"]
    if item.get("content") or item.get("content_bytes"):
        public["content"] = item.get("content") or item.get("content_bytes")
    return public


def _email_attachments(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    attachments: List[Dict[str, Any]] = []
    try:
        metadata = json.loads(row.get("metadata") or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    for item in metadata.get("attachments", []) if isinstance(metadata, dict) else []:
        public = _public_payload_attachment(item)
        if public:
            attachments.append(public)
    try:
        email_id = int(row.get("id"))
        attachments.extend(_public_storage_attachment(meta) for meta in attachment_storage.get_by_email(email_id))
    except Exception as exc:
        logger.debug("Unable to load attachments for email %s: %s", row.get("id"), exc)
    seen = set()
    unique = []
    for item in attachments:
        key = item.get("attachment_id") or item.get("filename")
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _with_email_attachments(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for row in rows:
        row["attachments"] = _email_attachments(row)
        row["has_attachments"] = bool(row["attachments"])
    return rows


def public_account(account: dict) -> dict:
    if not account:
        return {}
    diagnostic = get_db().get_latest_provider_diagnostic(account["id"])
    registry = ProviderCapabilityRegistry()
    capability = registry.get(account.get("provider"))
    return {
        "id": account["id"],
        "user_id": account["user_id"],
        "email": account["email"],
        "email_address": account.get("email_address") or account["email"],
        "display_name": account.get("display_name") or account["email"],
        "provider": account["provider"],
        "status": account.get("status") or "connected",
        "reconnect_state": account.get("reconnect_state") or "ok",
        "last_error": account.get("last_error"),
        "last_sync_at": account.get("last_sync_at"),
        "sync_checkpoint": account.get("sync_checkpoint"),
        "auth_type": account.get("auth_type"),
        "oauth_provider": account.get("oauth_provider"),
        "token_scopes": safe_json(account.get("token_scopes")) if isinstance(account.get("token_scopes"), str) else account.get("token_scopes"),
        "sync_status": account.get("sync_status"),
        "webhook_enabled": bool(account.get("webhook_enabled")) if account.get("webhook_enabled") is not None else None,
        "sync_enabled": bool(account.get("sync_enabled")) if account.get("sync_enabled") is not None else True,
        "created_at": account.get("created_at"),
        "updated_at": account.get("updated_at"),
        "metadata": safe_json(account.get("metadata")),
        "capabilities": capability.as_dict(),
        "diagnostic": diagnostic,
    }


def safe_json(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def ensure_local_user_id(db: Database, user_id: int = 0) -> int:
    """Return a valid user id for local-first operations.

    Extension/dashboard calls often send user_id=0 or user_id=1 before any
    account exists. Because feedback and rules have foreign keys to users,
    first-use writes must create or reuse the local user instead of failing.
    """
    if user_id and db.fetch_one("SELECT id FROM users WHERE id = ?", (user_id,)):
        return user_id
    return db.add_user("local@aiemailorganizer.local", "local")


def callback_url(request: Request, provider: str) -> str:
    host = request.url.hostname or "127.0.0.1"
    if host not in ("127.0.0.1", "localhost"):
        host = "127.0.0.1"
    port = f":{request.url.port}" if request.url.port else ""
    provider_path = {"gmail": "google", "google": "google", "outlook": "microsoft", "microsoft": "microsoft", "microsoft365": "microsoft", "exchange": "microsoft", "yahoo": "yahoo", "zoho": "zoho", "yandex": "yandex"}.get(provider, provider)
    return f"http://127.0.0.1{port}/api/v1/oauth/{provider_path}/callback"


def ensure_local_request(request: Request):
    client_host = request.client.host if request.client else "127.0.0.1"
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="OAuth callbacks are only accepted from localhost")


def oauth_result_page(provider: str, status: str, message: str, email: str = None) -> HTMLResponse:
    safe_provider = escape(provider)
    safe_status = escape(status)
    safe_message = escape(message)
    safe_email = escape(email or "")
    query = f"oauth={quote(status)}&provider={quote(provider)}"
    if email:
        query += f"&email={quote(email)}"
    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>AI Email Organizer OAuth</title></head>
<body>
  <main style="font-family:Segoe UI,Arial,sans-serif;max-width:640px;margin:12vh auto;padding:24px">
    <h1>{safe_provider.title()} connection {safe_status}</h1>
    <p>{safe_message}</p>
    <p>{safe_email}</p>
    <a href="/dashboard?{query}">Return to dashboard</a>
  </main>
  <script>setTimeout(() => {{ window.location.href = "/dashboard?{query}"; }}, 1200);</script>
</body>
</html>"""
    return HTMLResponse(html)




def oauth_setup_page(provider: str, status: dict, base_url: str, email: str = "") -> HTMLResponse:
    """Render a user-facing OAuth setup screen instead of exposing raw JSON."""
    requested = provider
    group = {"google": "gmail", "gmail": "gmail", "outlook": "microsoft", "microsoft365": "microsoft", "exchange": "microsoft", "yandex": "yandex"}.get(provider, provider)
    if group not in OAUTH_GROUPS:
        group = "gmail"
    meta = OAUTH_GROUPS[group]
    display = meta["display_name"]
    redirect = ProviderConfigManager().redirect_uri_for(group, base_url)
    console = meta["cloud_console_url"]
    tenant = '<label>Tenant ID <input id="tenantId" value="common"></label>' if group == "microsoft" else '<input id="tenantId" type="hidden" value="common">'
    safe_display = escape(display)
    safe_redirect = escape(redirect)
    safe_email = escape(email or "")
    safe_msg = escape(status.get("message") or status.get("client_message") or "OAuth app credentials are required before connecting this provider.")
    safe_console = escape(console)
    scope_html = "".join(f"<li>{escape(scope)}</li>" for scope in meta.get("scopes", []))
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{safe_display} OAuth Setup</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;background:#f7f8fb;color:#101828;margin:0}}main{{max-width:820px;margin:6vh auto;background:white;border:1px solid #e6e9ef;border-radius:24px;padding:28px;box-shadow:0 18px 60px rgba(16,24,40,.08)}}label{{display:grid;gap:7px;margin:12px 0;font-weight:700}}input{{padding:12px;border:1px solid #d0d5dd;border-radius:12px}}button,a.btn{{display:inline-block;border:0;border-radius:12px;background:#111827;color:white;padding:12px 16px;font-weight:800;text-decoration:none;margin-right:8px}}.muted{{color:#667085}}code{{display:block;background:#f8fafc;border:1px solid #e6e9ef;border-radius:12px;padding:12px;word-break:break-word}}.toast{{margin-top:14px;color:#065f46;font-weight:700}}.policy{{background:#ecfdf3;border:1px solid #abefc6;padding:10px 12px;border-radius:14px;color:#027a48;font-weight:700}}</style></head>
<body><main><h1>{safe_display} OAuth setup required</h1><p class="muted">{safe_msg}</p><p class="policy">OAuth providers never ask users for mailbox passwords or app passwords. Only provider app credentials are saved here by an admin.</p><p>Create or edit your OAuth app, add this redirect URI, then save the Client ID and Client Secret below.</p><code>{safe_redirect}</code><p><a href="{safe_console}" target="_blank" rel="noopener">Open provider console</a></p><h3>Requested permissions</h3><ul>{scope_html}</ul><label>Client ID <input id="clientId" autocomplete="off"></label><label>Client Secret <input id="clientSecret" type="password" autocomplete="new-password"></label>{tenant}<button id="saveBtn">Save OAuth & Continue</button><a class="btn" href="/dashboard">Return to Dashboard</a><div id="msg" class="toast"></div></main>
<script>
const provider={json.dumps(group)}; const email={json.dumps(email or '')}; const redirect_uri={json.dumps(redirect)};
document.getElementById('saveBtn').addEventListener('click', async () => {{
  const payload={{provider,email_address:email,client_id:document.getElementById('clientId').value.trim(),client_secret:document.getElementById('clientSecret').value,tenant_id:document.getElementById('tenantId').value||'common',redirect_uri,provider_options:{{}}}};
  if(!payload.client_id||!payload.client_secret){{document.getElementById('msg').textContent='Client ID and Client Secret are required.';return;}}
  const res=await fetch('/api/v1/oauth/config',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});
  if(!res.ok){{document.getElementById('msg').textContent='Save failed. Check credentials and try again.';return;}}
  document.getElementById('msg').textContent='Saved for '+(email||provider)+'. Return to Accounts and continue OAuth for that mailbox.';
}});
</script></body></html>"""
    return HTMLResponse(html, status_code=200)


def coerce_positive_int(value, default: int = 0) -> int:
    try:
        value = int(value)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default

def provider_sync_task(account_id: int, provider: str, max_results: int, sync_id: int):
    result = MailboxOrchestrator(get_db()).sync_account(account_id, max_results=max_results, sync_id=sync_id)
    if not result.get("ok"):
        raise RuntimeError(result.get("message") or result.get("status") or f"Sync failed for {provider}")
    return result.get("detail", {}).get("processed", 0)


class EmailInput(BaseModel):
    subject: str = Field(..., max_length=500)
    sender: str = Field(..., max_length=200)
    sender_email: str = Field(..., max_length=300)
    body: Optional[str] = Field(default="", max_length=50000)
    message_id: Optional[str] = Field(default=None, max_length=200)

    @field_validator("subject", "sender", "sender_email")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            return ""
        return v.strip()


class ClassificationOutput(BaseModel):
    category: str
    confidence: float
    priority: str
    action: str
    timestamp: str
    source: Optional[str] = None
    scam_reasons: List[str] = Field(default_factory=list)


class FeedbackInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    email_id: Optional[Union[int, str]] = Field(default=0)
    predicted_category: str = Field(..., max_length=50)
    actual_category: str = Field(..., max_length=50, validation_alias=AliasChoices("actual_category", "correct_category"))
    user_id: int = Field(default=0, ge=0)

    @field_validator("predicted_category", "actual_category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        v = normalize_feedback_category(v)
        if v not in VALID_CATEGORIES:
            return "Personal"
        return v


class RuleInput(BaseModel):
    user_id: int = Field(..., ge=0)
    name: str = Field(..., max_length=100)
    condition: str = Field(..., max_length=2000)
    action: str = Field(..., max_length=3000)


class SearchInput(BaseModel):
    query: str = Field(..., max_length=200)
    category: Optional[str] = Field(default=None, max_length=50)
    limit: int = Field(default=50, ge=1, le=1000)


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str = "9.7.0"


class OAuthStartRequest(BaseModel):
    redirect_after: Optional[str] = Field(default="/dashboard", max_length=500)
    email: Optional[str] = Field(default=None, max_length=300)

    @field_validator("email")
    @classmethod
    def normalize_optional_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        email = value.strip().lower()
        if not email:
            return None
        if "@" not in email:
            raise ValueError("Valid email is required")
        return email


class ProviderDetectRequest(BaseModel):
    email: str = Field(..., max_length=300)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Valid email is required")
        return email


class ProviderOAuthConfigRequest(BaseModel):
    provider: str = Field(..., max_length=40)
    email_address: Optional[str] = Field(default=None, max_length=300)
    client_id: str = Field(..., max_length=500)
    client_secret: str = Field(..., max_length=1000)
    tenant_id: Optional[str] = Field(default="common", max_length=200)
    redirect_uri: Optional[str] = Field(default=None, max_length=500)
    provider_options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("email_address")
    @classmethod
    def normalize_config_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        email = value.strip().lower()
        if not email:
            return None
        if "@" not in email:
            raise ValueError("Valid email is required")
        return email

class AccountAddRequest(BaseModel):
    provider: str = Field(..., max_length=30)
    email: str = Field(..., max_length=300)
    password: Optional[str] = Field(default=None, max_length=1000)
    host: Optional[str] = Field(default=None, max_length=300)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    security: Optional[str] = Field(default="ssl", max_length=20)
    imap_host: Optional[str] = Field(default=None, max_length=300)
    imap_port: Optional[int] = Field(default=None, ge=1, le=65535)
    smtp_host: Optional[str] = Field(default=None, max_length=300)
    smtp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    ssl: Optional[bool] = Field(default=True)
    sync_interval: Optional[int] = Field(default=20, ge=20, le=60)
    connection_method: Optional[str] = Field(default=None, max_length=30)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        provider = (value or "").strip().lower()
        registry = ProviderCapabilityRegistry()
        if provider not in registry.supported() and provider not in {"microsoft365", "selfhosted", "self-hosted"}:
            # Unknown values are accepted as custom providers only when host metadata is supplied.
            provider = "custom"
        if provider == "selfhosted" or provider == "self-hosted":
            provider = "self_hosted"
        return provider

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if "@" not in email:
            raise ValueError("Valid email is required")
        return email


class AccountRemoveRequest(BaseModel):
    account_id: int = Field(..., ge=1)


class AccountReconnectRequest(BaseModel):
    password: Optional[str] = Field(default=None, max_length=1000)
    host: Optional[str] = Field(default=None, max_length=300)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    security: Optional[str] = Field(default=None, max_length=20)


class AccountUpdateRequest(BaseModel):
    password: Optional[str] = Field(default=None, max_length=1000)
    imap_host: Optional[str] = Field(default=None, max_length=300)
    imap_port: Optional[int] = Field(default=None, ge=1, le=65535)
    smtp_host: Optional[str] = Field(default=None, max_length=300)
    smtp_port: Optional[int] = Field(default=None, ge=1, le=65535)
    ssl: Optional[bool] = Field(default=None)
    sync_interval: Optional[int] = Field(default=None, ge=20, le=60)
    security: Optional[str] = Field(default=None, max_length=20)


class SyncStartRequest(BaseModel):
    account_id: Optional[int] = Field(default=None, ge=1)
    provider: Optional[str] = Field(default=None, max_length=30)
    max_results: int = Field(default=50, ge=1, le=500)


class MailboxBucketCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = (value or "").strip()
        if not name:
            raise ValueError("Name is required")
        return name


class CategoryUpdateInput(BaseModel):
    category: str = Field(..., max_length=50)
    user_id: int = Field(default=0, ge=0)


class ScamVerdictInput(BaseModel):
    email_id: int = Field(..., ge=1)
    category: str = Field(..., max_length=20)
    user_id: int = Field(default=0, ge=0)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    try:
        db = get_db()
        status = db.get_connection_status()

        if status.get("status") == "healthy":
            return HealthResponse(
                status="healthy",
                timestamp=datetime.now().isoformat()
            )
        else:
            return HealthResponse(
                status="degraded",
                timestamp=datetime.now().isoformat()
            )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            timestamp=datetime.now().isoformat()
        )


@router.post("/classify", response_model=ClassificationOutput)
async def classify_email(email: EmailInput):
    try:
        classifier = get_classifier()
        result = classifier.classify(
            subject=email.subject,
            sender=email.sender,
            sender_email=email.sender_email,
            body=email.body or ""
        )

        action = "auto_move" if result["confidence"] > 0.95 else \
                  "suggest" if result["confidence"] > 0.70 else "none"

        return ClassificationOutput(
            category=result["category"],
            confidence=result["confidence"],
            priority=result["priority"],
            action=action,
            timestamp=result["timestamp"],
            source=result.get("source"),
            scam_reasons=result.get("scam_reasons", []),
        )
    except Exception as e:
        logger.error(f"Classification error: {e}")
        raise HTTPException(status_code=500, detail=f"Classification failed: {str(e)}")


@router.post("/feedback")
async def submit_feedback(feedback: FeedbackInput):
    try:
        db = get_db()
        classifier = get_classifier()

        email_id = coerce_positive_int(feedback.email_id)
        stored = False
        if email_id and db.fetch_one("SELECT id FROM emails WHERE id = ?", (email_id,)):
            db.add_feedback(
                email_id=email_id,
                predicted_category=feedback.predicted_category,
                actual_category=feedback.actual_category,
                user_id=ensure_local_user_id(db, feedback.user_id)
            )
            stored = True
            if feedback.actual_category in FEEDBACK_CATEGORIES:
                _apply_manual_email_category(db, email_id, feedback.actual_category)
                db.record_classification_override(
                    email_id=email_id,
                    category=feedback.actual_category,
                    user_id=ensure_local_user_id(db, feedback.user_id),
                )

        classifier.learn_from_feedback(
            predicted_category=feedback.predicted_category,
            actual_category=feedback.actual_category
        )

        return {"status": "success", "message": "Feedback recorded", "stored": stored}
    except Exception as e:
        logger.error(f"Feedback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rules/create")
async def create_rule(rule: RuleInput):
    try:
        db = get_db()
        from backend.rules.engine import parse_stored_value, normalize_actions
        from backend.rules.action_executor import RuleActionExecutor

        condition_payload = parse_stored_value(rule.condition, {"type": "always", "value": []})
        action_payload = normalize_actions(rule.action)
        if not action_payload:
            raise HTTPException(status_code=400, detail="At least one valid rule action is required")

        rule_id = db.add_rule(
            user_id=ensure_local_user_id(db, rule.user_id),
            name=rule.name,
            condition=json.dumps(condition_payload, sort_keys=True),
            action=json.dumps(action_payload, sort_keys=True)
        )
        apply_summary = RuleActionExecutor(db, enable_provider_write=False).apply_rules_to_existing_emails(limit=1000)
        return {"status": "success", "rule_id": rule_id, "apply_summary": apply_summary}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Rule creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rules/stats")
async def get_rules_stats_compat():
    """Expose rule-engine statistics before /rules/{user_id} captures static paths."""
    try:
        from backend.api.rules import rule_engine
        return rule_engine.get_statistics()
    except Exception as e:
        logger.error(f"Rule stats error: {e}")
        return {"total_rules": 0, "enabled_rules": 0, "executions": 0}


@router.get("/rules/{user_id:int}")
async def get_rules(user_id: int):
    try:
        db = get_db()
        rules = db.get_rules_by_user(user_id)
        return {"rules": rules}
    except Exception as e:
        logger.error(f"Get rules error: {e}")
        return {"rules": []}


@router.post("/search")
async def search_emails(search: SearchInput):
    try:
        db = get_db()

        query_base = f"%{search.query}%"

        if search.category:
            emails = db.fetch_all(
                "SELECT * FROM emails WHERE (subject LIKE ? OR body_text LIKE ?) AND category = ? ORDER BY created_at DESC LIMIT ?",
                (query_base, query_base, search.category, search.limit)
            )
        else:
            emails = db.fetch_all(
                "SELECT * FROM emails WHERE subject LIKE ? OR body_text LIKE ? ORDER BY created_at DESC LIMIT ?",
                (query_base, query_base, search.limit)
            )

        return {"emails": emails, "count": len(emails)}
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"emails": [], "count": 0, "error": str(e)}


@router.get("/categories")
async def get_categories():
    try:
        db = get_db()
        categories = db.get_all_categories()
        return {"categories": [c["category"] for c in categories]}
    except Exception as e:
        logger.error(f"Get categories error: {e}")
        return {"categories": []}


@router.get("/smart-views")
async def get_smart_views():
    try:
        classifier = get_classifier()
        return {"views": classifier.get_smart_views()}
    except Exception as e:
        logger.error(f"Get smart views error: {e}")
        return {"views": ["Urgent", "Finance", "Clients"]}


@router.get("/stats")
async def get_stats():
    try:
        db = get_db()
        feedback_count = db.get_feedback_count()

        classifier = get_classifier()
        classifier_stats = classifier.get_stats()

        return {
            "total_feedback": feedback_count["count"] if feedback_count else 0,
            "classifier_stats": classifier_stats
        }
    except Exception as e:
        logger.error(f"Get stats error: {e}")
        return {"total_feedback": 0, "classifier_stats": {}}


@router.post("/email/process")
async def process_email(email: EmailInput):
    try:
        classifier = get_classifier()
        db = get_db()

        result = classifier.classify(
            subject=email.subject,
            sender=email.sender,
            sender_email=email.sender_email,
            body=email.body or ""
        )

        # Store email if account exists
        account = db.get_account_by_email(email.sender_email)
        if account:
            email_id = db.add_email(
                account_id=account["id"],
                message_id=email.message_id or "",
                subject=email.subject,
                sender=email.sender,
                sender_email=email.sender_email,
                body_text=email.body,
                category=result["category"],
                confidence=result["confidence"],
                priority=result["priority"]
            )
            rule_summary = None
            try:
                from backend.rules.action_executor import RuleActionExecutor
                rule_summary = RuleActionExecutor(db, enable_provider_write=False).apply_rules_to_email_id(email_id)
            except Exception as exc:
                logger.warning("Rule execution failed for processed email %s: %s", email_id, exc)

            # Emit WS alert + event bus for high-confidence scam detections
            try:
                cat = result.get("category", "")
                conf = result.get("confidence", 0)
                if cat in ("Scam", "Phishing", "Spam") and conf >= 0.7:
                    from backend.api.ws_alerts import emit_scam_detected
                    asyncio.create_task(emit_scam_detected(
                        email_id=str(email_id),
                        sender_email=email.sender_email or "",
                        subject=email.subject or "",
                        confidence=conf,
                        reasons=result.get("scam_reasons", []),
                        category=cat,
                    ))
            except Exception:
                pass

            return {"status": "success", "email_id": email_id, "classification": result, "rule_summary": rule_summary}

        return {"status": "success", "classification": result}
    except Exception as e:
        logger.error(f"Process email error: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/email/{email_id}")
async def get_email(email_id: int):
    try:
        db = get_db()
        email = db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))

        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        return email
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get email error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _apply_manual_email_category(db: Database, email_id: int, category: str) -> None:
    if category == "Scam":
        db.update_email_category(email_id, "Scam", 1.0)
        db.add_email_label(email_id, "Scam")
        db.set_email_folder(email_id, "Scam")
        db.execute("UPDATE emails SET priority = ? WHERE id = ?", ("Critical", email_id))
    elif category == "Normal":
        db.update_email_category(email_id, "Normal", 1.0)
        db.add_email_label(email_id, "Normal")
        db.set_email_folder(email_id, "INBOX")
        db.execute("UPDATE emails SET priority = ? WHERE id = ?", ("Medium", email_id))
    else:
        db.update_email_category(email_id, category, 0.95)


def _record_onnx_learning_from_email(email: Dict[str, Any], predicted_category: str, actual_category: str) -> Optional[Dict[str, Any]]:
    if actual_category not in FEEDBACK_CATEGORIES:
        return None
    try:
        return get_onnx_control_plane().record_feedback({
            "subject": email.get("subject") or "",
            "sender": email.get("sender") or "",
            "sender_email": email.get("sender_email") or "",
            "body": email.get("body_text") or email.get("body") or "",
            "predicted_category": predicted_category or "",
            "actual_category": actual_category,
            "priority": "Critical" if actual_category == "Scam" else "Medium",
            "scope": "sender",
        })
    except Exception as exc:  # noqa: BLE001 - learning must not block manual verdicts
        logger.warning("ONNX learning feedback skipped for email %s: %s", email.get("id"), exc)
        return {"status": "skipped", "reason": str(exc)}


@router.put("/email/{email_id}/category")
async def update_email_category(
    email_id: int,
    payload: Optional[CategoryUpdateInput] = Body(default=None),
    category: Optional[str] = None,
    user_id: int = 0,
):
    try:
        if payload is not None:
            category = payload.category
            user_id = payload.user_id

        category = normalize_feedback_category(category)

        if category not in VALID_CATEGORIES:
            category = "Personal"

        db = get_db()
        email = db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
        if not email:
            raise HTTPException(status_code=404, detail="Email not found")

        predicted_category = email.get("category", "")
        local_user_id = ensure_local_user_id(db, user_id)
        _apply_manual_email_category(db, email_id, category)

        # Record feedback after preserving the previous category.
        db.add_feedback(
            email_id=email_id,
            predicted_category=predicted_category,
            actual_category=category,
            user_id=local_user_id
        )

        future_filter = None
        if category in FEEDBACK_CATEGORIES:
            future_filter = db.record_classification_override(email_id=email_id, category=category, user_id=local_user_id)
            learning_feedback = _record_onnx_learning_from_email(email, predicted_category, category)
            global _classifier
            _classifier = EmailClassifier(db=db)
        else:
            learning_feedback = None

        return {
            "status": "success",
            "message": f"Category updated to {category}",
            "category": category,
            "future_filter": future_filter,
            "learning_feedback": learning_feedback,
        }
    except Exception as e:
        logger.error(f"Update category error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/email/{email_id}/archive")
async def archive_email(email_id: int):
    db = get_db()
    if not db.fetch_one("SELECT id FROM emails WHERE id = ?", (email_id,)):
        raise HTTPException(status_code=404, detail="Email not found")
    db.set_email_folder(email_id, "Archive")
    db.execute("UPDATE emails SET is_read = 1 WHERE id = ?", (email_id,))
    return {"status": "archived", "email_id": email_id, "folder": "Archive"}


@router.post("/email/{email_id}/label")
async def add_label_to_email(email_id: int, payload: dict = Body(default={})):
    label = (payload.get("label") or "").strip()
    if not label or len(label) > 100:
        raise HTTPException(status_code=400, detail="Label required (max 100 chars)")
    db = get_db()
    if not db.fetch_one("SELECT id FROM emails WHERE id = ?", (email_id,)):
        raise HTTPException(status_code=404, detail="Email not found")
    db.add_email_label(email_id, label)
    return {"status": "labeled", "email_id": email_id, "label": label}


@router.post("/email/{email_id}/move")
async def move_email_to_folder(email_id: int, payload: dict = Body(default={})):
    folder = (payload.get("folder") or "").strip()
    if not folder or len(folder) > 100:
        raise HTTPException(status_code=400, detail="Folder name required (max 100 chars)")
    db = get_db()
    if not db.fetch_one("SELECT id FROM emails WHERE id = ?", (email_id,)):
        raise HTTPException(status_code=404, detail="Email not found")
    db.set_email_folder(email_id, folder)
    return {"status": "moved", "email_id": email_id, "folder": folder}


@router.post("/scam-filter/verdict")
async def save_scam_filter_verdict(payload: ScamVerdictInput):
    category = normalize_feedback_category(payload.category)
    if category not in FEEDBACK_CATEGORIES:
        raise HTTPException(status_code=400, detail="Verdict must be Scam or Normal")
    return await update_email_category(
        payload.email_id,
        CategoryUpdateInput(category=category, user_id=payload.user_id),
    )


@router.get("/scam-filter/overrides")
async def get_scam_filter_overrides(user_id: int = 0, limit: int = 100):
    db = get_db()
    local_user_id = user_id if user_id and db.fetch_one("SELECT id FROM users WHERE id = ?", (user_id,)) else None
    rows = db.list_classification_overrides(user_id=local_user_id, limit=limit)
    return {"overrides": rows, "count": len(rows)}

MANUAL_CONNECTION_METHODS = {"app_password", "imap", "imap_smtp", "advanced_imap", "manual", "password"}
OAUTH_CONNECTION_METHODS = {"oauth", "oauth2", "provider_oauth"}


def _oauth_group_for_provider(provider: str) -> Optional[str]:
    provider = ProviderCapabilityRegistry.normalize(provider)
    if provider == "gmail":
        return "gmail"
    if provider in {"outlook", "microsoft365", "exchange"}:
        return "microsoft"
    if provider in {"yahoo", "zoho", "yandex"}:
        return provider
    return oauth_group_for(provider)


def _oauth_config_key(group: str) -> str:
    return {"google": "gmail", "gmail": "gmail", "outlook": "microsoft", "microsoft": "microsoft", "yahoo": "yahoo", "zoho": "zoho", "yandex": "yandex"}.get(group, group)


def _oauth_start_for_group(group: str, email: str = "") -> str:
    group = _oauth_config_key(group)
    path = {
        "gmail": "/api/v1/oauth/google/start",
        "microsoft": "/api/v1/oauth/microsoft/start",
        "yahoo": "/api/v1/oauth/yahoo/start",
        "zoho": "/api/v1/oauth/zoho/start",
        "yandex": "/api/v1/oauth/yandex/start",
    }.get(group, "/api/v1/oauth/google/start")
    return f"{path}?email={quote(email or '')}" if email else path


def _resolve_account_connection(request_data: "AccountAddRequest") -> Dict[str, Any]:
    provider = ProviderCapabilityRegistry.normalize(request_data.provider)
    if provider == "microsoft365":
        provider = "microsoft365"
    detected = detect_mail_provider(request_data.email)
    persistence_defaults = detect_mail_settings(request_data.email)
    capability = ProviderCapabilityRegistry().get(provider)
    detected_defaults = detected.get("defaults") or {}
    imap_host = request_data.imap_host or request_data.host or detected_defaults.get("imap_host") or persistence_defaults.get("imap_host") or capability.default_imap_host
    imap_port = int(request_data.imap_port or request_data.port or detected_defaults.get("imap_port") or persistence_defaults.get("imap_port") or capability.default_imap_port or 993)
    smtp_host = request_data.smtp_host or detected_defaults.get("smtp_host") or persistence_defaults.get("smtp_host") or capability.default_smtp_host
    smtp_port = int(request_data.smtp_port or detected_defaults.get("smtp_port") or persistence_defaults.get("smtp_port") or capability.default_smtp_port or 465)
    security = (request_data.security or detected_defaults.get("imap_security") or "ssl").lower()
    sync_interval = request_data.sync_interval if request_data.sync_interval in (20, 30, 60) else 20
    oauth_group = _oauth_group_for_provider(provider)
    method = (request_data.connection_method or ("oauth" if oauth_group and not request_data.password else "app_password")).strip().lower()
    if method in {"default", "auto"}:
        method = "oauth" if oauth_group and not request_data.password else "app_password"
    manual_provider = provider if ProviderCapabilityRegistry().get(provider).supports_imap else "imap"
    metadata = account_metadata(
        sync_interval,
        auth_type=capability.auth_type,
        credential_storage="encrypted_local_vault",
        manual_removal_only=True,
        preserve_on_restart=True,
        preserve_on_update=True,
        preserve_on_crash=True,
        provider=provider,
        mail_provider=provider,
        connection_method=method,
        host=imap_host,
        port=imap_port,
        security=security,
        imap_host=imap_host,
        imap_port=imap_port,
        imap_security=security,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_security="ssl" if int(smtp_port or 465) == 465 else "starttls",
        ssl=bool(request_data.ssl),
        account_editable=True,
    )
    return {
        "provider": provider,
        "capability": capability,
        "oauth_group": oauth_group,
        "method": method,
        "manual_provider": manual_provider,
        "imap_host": imap_host,
        "imap_port": imap_port,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "security": security,
        "sync_interval": sync_interval,
        "metadata": metadata,
        "detected": detected,
    }


def _oauth_status_detail(provider: str, group: str, request: Request = None, email: str = "") -> Dict[str, Any]:
    base_url = request_base_url(request) if request else None
    config_key = _oauth_config_key(group)
    status = ProviderConfigManager().status(config_key, base_url, email_address=email)
    configured = bool(status.get("configured"))
    return {
        "ok": configured,
        "status": "oauth_ready" if configured else "provider_setup_required",
        "provider": provider,
        "oauth_provider": config_key,
        "configured": configured,
        "setup_required": not configured,
        "oauth_start_url": _oauth_start_for_group(config_key, email),
        "setup_url": "/dashboard#accounts-oauth-setup",
        "requires_password": False,
        "password_required": False,
        "app_password_required": False,
        "configuration": status,
        "client_message": "OAuth is ready. Continue with the official provider sign-in page." if configured else "No OAuth configuration found for this provider/email. Please configure OAuth app details first.",
    }


@router.post("/accounts/test")
async def test_account_connection(request: Request, request_data: AccountAddRequest):
    """Validate the selected account path before saving.

    OAuth providers return a provider setup/sign-in state. IMAP/app-password
    providers perform a real IMAP login test when credentials are present. A
    failed test never deletes or overwrites existing accounts.
    """
    ensure_local_request(request)
    resolved = _resolve_account_connection(request_data)
    provider = resolved["provider"]
    method = resolved["method"]
    oauth_group = resolved["oauth_group"]
    if oauth_group and method in OAUTH_CONNECTION_METHODS:
        detail = _oauth_status_detail(provider, oauth_group, request, request_data.email)
        detail["defaults"] = {
            "imap_host": resolved["imap_host"], "imap_port": resolved["imap_port"],
            "smtp_host": resolved["smtp_host"], "smtp_port": resolved["smtp_port"], "security": resolved["security"],
        }
        return detail
    if not request_data.password:
        return {
            "ok": False,
            "status": "credential_required",
            "provider": provider,
            "client_message": "Enter the mailbox app password/password before testing IMAP/SMTP.",
            "defaults": resolved["metadata"],
        }
    diagnostics = IMAPAccountManager(get_db()).validate(
        email=request_data.email,
        password=request_data.password,
        provider=resolved["manual_provider"],
        host=resolved["imap_host"],
        port=resolved["imap_port"],
        security=resolved["security"],
        timeout=8,
    )
    return {
        "ok": bool(diagnostics.get("ok")),
        "status": diagnostics.get("status", "unknown"),
        "provider": provider,
        "connection_method": method,
        "client_message": diagnostics.get("message") or ("Connection validated." if diagnostics.get("ok") else "Connection test failed."),
        "diagnostic": diagnostics,
        "defaults": resolved["metadata"],
    }



@router.get("/provider-config/status")
async def provider_config_status(request: Request):
    ensure_local_request(request)
    return ProviderConfigManager().all_status(base_url=request_base_url(request))


@router.get("/provider-config/instructions")
async def provider_config_instructions(request: Request):
    ensure_local_request(request)
    return ProviderConfigManager().instructions(base_url=request_base_url(request))


@router.post("/provider-config/oauth")
async def save_provider_oauth_config(request: Request, payload: ProviderOAuthConfigRequest):
    ensure_local_request(request)
    try:
        status = ProviderConfigManager().save_oauth_config(
            provider=payload.provider,
            client_id=payload.client_id,
            client_secret=payload.client_secret,
            tenant_id=payload.tenant_id,
            redirect_uri=payload.redirect_uri,
            email_address=payload.email_address,
            provider_options=payload.provider_options,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"status": "invalid_provider_config", "message": str(exc)})
    return {"status": "saved", "provider": status["provider"], "configuration": status}


@router.delete("/provider-config/oauth/{provider}")
async def clear_provider_oauth_config(request: Request, provider: str):
    ensure_local_request(request)
    try:
        status = ProviderConfigManager().clear_oauth_config(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"status": "invalid_provider_config", "message": str(exc)})
    return {"status": "cleared", "provider": status["provider"], "configuration": status}


# Provider / mailbox orchestration endpoints
@router.get("/providers")
async def provider_capabilities(request: Request):
    registry = ProviderCapabilityRegistry()
    manager = ProviderConfigManager()
    providers = []
    for provider in registry.list():
        provider["configuration"] = manager.status(provider.get("provider"), request_base_url(request))
        providers.append(provider)
    return {"providers": providers, "configuration": manager.all_status(base_url=request_base_url(request))}


@router.get("/mailbox/health")
async def mailbox_health(account_id: int = None):
    orchestrator = MailboxOrchestrator(get_db())
    return orchestrator.health(account_id)


@router.post("/mailbox/health/scan")
async def mailbox_health_scan():
    return {"results": MailboxHealthMonitor(get_db()).scan()}


@router.post("/accounts/detect")
async def detect_account_provider(request: Request, payload: ProviderDetectRequest):
    ensure_local_request(request)
    return detect_mail_provider(payload.email, request_base_url(request))


@router.get("/accounts/detect")
async def detect_account_provider_get(request: Request, email: str):
    ensure_local_request(request)
    return detect_mail_provider(email, request_base_url(request))


@router.post("/auth/strategy")
async def auth_strategy(request: Request, payload: dict = Body(default={})):
    ensure_local_request(request)
    try:
        email = payload.get("email") or ""
        provider = payload.get("provider")
        method = payload.get("connection_method") or payload.get("auth_method") or "auto"
        return UniversalEmailAuthEngine().onboarding_plan(email, provider=provider, requested_method=method, base_url=request_base_url(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"status": "invalid_email", "message": str(exc)})


@router.post("/auth/validate")
async def auth_validate(request: Request, payload: dict = Body(default={})):
    ensure_local_request(request)
    try:
        return UniversalEmailAuthEngine().validate_account_payload(payload, base_url=request_base_url(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"status": "invalid_email", "message": str(exc)})


# Account Endpoints
@router.post("/accounts/add")
async def add_account(request_data: AccountAddRequest):
    """Create/connect an account through a validated local-first flow.

    OAuth-capable providers return an explicit sign-in/setup response. Manual
    providers are validated through IMAP before being marked connected. If a
    manual credential test fails, the account is preserved as needs_reconnect so
    users can repair it; it is never silently deleted.
    """
    db = get_db()
    resolved = _resolve_account_connection(request_data)
    provider = resolved["provider"]
    method = resolved["method"]
    oauth_group = resolved["oauth_group"]
    metadata = resolved["metadata"]
    strategy = UniversalEmailAuthEngine().strategy_for(
        request_data.email, provider=provider, requested_method=method, base_url=None
    )
    metadata.update({
        "auth_strategy": strategy.as_dict(),
        "password_required": strategy.password_required if method in OAUTH_CONNECTION_METHODS else True,
        "app_password_required": strategy.app_password_required if method not in OAUTH_CONNECTION_METHODS else False,
        "validate_oauth_tokens_only": bool(method in OAUTH_CONNECTION_METHODS),
    })

    if oauth_group and method in OAUTH_CONNECTION_METHODS:
        detail = _oauth_status_detail(provider, oauth_group, None, request_data.email)
        detail.update({
            "message": detail["client_message"],
            "defaults": metadata,
        })
        raise HTTPException(status_code=428 if not detail["configured"] else 409, detail=detail)

    if not request_data.password:
        raise HTTPException(status_code=400, detail={
            "status": "credential_required",
            "message": "Manual IMAP/App Password credentials are required for this non-OAuth path. OAuth providers must use provider sign-in and never require mailbox passwords.",
            "provider": provider,
            "defaults": metadata,
        })

    diagnostics = IMAPAccountManager(db).validate(
        email=request_data.email,
        password=request_data.password,
        provider=resolved["manual_provider"],
        host=resolved["imap_host"],
        port=resolved["imap_port"],
        security=resolved["security"],
        timeout=8,
    )
    metadata["last_connection_test"] = diagnostics
    encrypted_secret = TokenCipher().encrypt(request_data.password)
    validation_status = diagnostics.get("status") or "unknown"
    validation_ok = bool(diagnostics.get("ok"))
    # Network/DNS failures can happen while the user is offline. Preserve the
    # account as connected and let background sync retry later. Definite auth or
    # configuration failures are saved as reconnect-required for repair.
    deferred_statuses = {"network_error", "timeout", "temporary_failure"}
    hard_failures = {"auth_failed", "invalid_input", "configuration_required", "sync_not_supported"}
    connected = validation_ok or validation_status in deferred_statuses
    status = "connected" if connected else "needs_reconnect"
    reconnect_state = "ok" if (validation_ok or validation_status in deferred_statuses) else (validation_status or "validation_failed")
    if validation_ok:
        message = "Account validated, saved securely and queued for sync."
    elif validation_status in deferred_statuses:
        metadata["validation_deferred"] = True
        message = "Account saved securely. Network validation could not complete, so sync will retry automatically and the account will not be removed."
    else:
        message = "Account saved for repair. Connection validation failed; use Repair/Reconnect to update credentials."
    capability = resolved["capability"]
    account_id = db.upsert_account(
        provider=provider,
        email=request_data.email,
        refresh_token=encrypted_secret,
        status=status,
        reconnect_state=reconnect_state,
        last_error=None if connected else diagnostics.get("message"),
        metadata=metadata,
        auth_type="imap" if method in MANUAL_CONNECTION_METHODS else capability.auth_type,
        oauth_provider=None,
        token_scopes="[]",
        sync_status="pending" if connected else "blocked",
        webhook_enabled=0,
        provider_capabilities=json.dumps(capability.as_dict(), sort_keys=True),
    )
    db.add_provider_diagnostic(account_id, provider, diagnostics.get("status", "saved"), {
        "status": diagnostics.get("status", "saved"),
        "ok": connected,
        "message": diagnostics.get("message") or message,
        "metadata": metadata,
        "manual_removal_only": True,
    })
    structure = None
    if connected:
        try:
            structure = ProviderMailboxTaxonomy(db).sync_mailbox_structure(account_id)
        except Exception as exc:
            logger.debug("Folder/label discovery did not complete for account %s: %s", account_id, exc)
            structure = {"ok": False, "message": str(exc)}
    sync_id = db.add_sync_status(account_id, "pending" if connected else "blocked")
    if not connected:
        db.update_sync_status(sync_id, "failed", error=diagnostics.get("message") or diagnostics.get("status"))
    return {
        "status": "saved",
        "connection_status": "connected" if connected else "needs_repair",
        "ok": connected,
        "message": message,
        "account": public_account(db.get_account_by_id(account_id)),
        "connection_test": diagnostics,
        "structure_sync": structure,
        "sync": {"status": "pending" if connected else "blocked", "interval": resolved["sync_interval"], "sync_id": sync_id},
        "next_step": "sync" if connected else "repair_credentials",
    }


@router.get("/accounts/{account_id}/preview")
async def account_inbox_preview(account_id: int, limit: int = 10):
    db = get_db()
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    emails = db.fetch_all("SELECT id, subject, sender, sender_email, category, priority, created_at FROM emails WHERE account_id = ? ORDER BY created_at DESC LIMIT ?", (account_id, min(max(int(limit or 10), 1), 50)))
    return {"status": "ready", "account": public_account(account), "emails": emails, "count": len(emails)}


@router.post("/accounts/{account_id}/finish")
async def finish_account_setup(account_id: int):
    db = get_db()
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    preview = await account_inbox_preview(account_id, 10)
    latest_sync = db.fetch_one("SELECT * FROM sync_status WHERE account_id = ? ORDER BY started_at DESC LIMIT 1", (account_id,))
    return {"status": "finished", "account": public_account(account), "latest_sync": latest_sync, "preview": preview}



@router.post("/accounts")
async def add_account_compat(request_data: AccountAddRequest):
    return await add_account(request_data)


@router.get("/accounts")
async def get_accounts(user_id: int = None):
    db = get_db()
    accounts = db.get_accounts_by_user(user_id) if user_id else db.get_all_accounts()
    return {"accounts": [public_account(account) for account in accounts]}


def _mailbox_source(account: dict) -> dict:
    public = public_account(account)
    public["mailbox_id"] = public["id"]
    return public


@router.get("/mailboxes")
async def get_mailboxes(user_id: int = None):
    db = get_db()
    accounts = db.get_accounts_by_user(user_id) if user_id else db.get_all_accounts()
    mailboxes = [_mailbox_source(account) for account in accounts]
    return {"mailboxes": mailboxes, "accounts": mailboxes, "count": len(mailboxes)}


def _parse_email_labels(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except (TypeError, json.JSONDecodeError):
        pass
    return [part.strip() for part in text.split(",") if part.strip()]


def _public_email_row(row: dict) -> dict:
    row = dict(row or {})
    mailbox_id = row.get("mailbox_id") or row.get("account_id")
    provider = row.get("account_provider") or row.get("provider")
    email_address = row.get("account_email") or row.get("email_address")
    labels = _parse_email_labels(row.get("labels"))
    row.update({
        "mailbox_id": mailbox_id,
        "account_id": row.get("account_id") or mailbox_id,
        "provider": provider,
        "email_address": email_address,
        "account_email": email_address,
        "account_display_name": row.get("account_display_name") or email_address,
        "provider_message_id": row.get("provider_message_id") or row.get("message_id"),
        "snippet": row.get("snippet") or (row.get("body_text") or "")[:240],
        "labels": labels,
        "label_names": labels,
        "source": {
            "mailbox_id": mailbox_id,
            "provider": provider,
            "email_address": email_address,
            "display_name": row.get("account_display_name") or email_address,
        },
    })
    return row


def _query_inbox_rows(
    db: Database,
    limit: int = 50,
    mailbox_id: int = None,
    provider: str = None,
    folder_id: int = None,
    label_id: int = None,
    unread: bool = None,
    category: str = None,
    folder: str = None,
    label: str = None,
    cursor: int = None,
    page: int = None,
) -> List[dict]:
    limit = min(max(int(limit or 50), 1), 1000)
    where = ["COALESCE(e.delete_state, 'active') != 'deleted'"]
    params: List[Any] = []
    if mailbox_id:
        where.append("e.account_id = ?")
        params.append(int(mailbox_id))
    if provider:
        where.append("LOWER(COALESCE(a.provider, e.provider, '')) = ?")
        params.append(ProviderCapabilityRegistry.normalize(provider))
    if category:
        where.append("e.category = ?")
        params.append(category)
    if unread is not None:
        where.append("COALESCE(e.is_read, 0) = ?")
        params.append(0 if unread else 1)
    if folder_id:
        folder_row = db.fetch_one("SELECT * FROM mail_folders WHERE id = ?", (int(folder_id),))
        if not folder_row:
            return []
        where.append("e.account_id = ? AND e.folder = ?")
        params.extend([folder_row.get("account_id") or folder_row.get("mailbox_id"), folder_row.get("name")])
    elif folder:
        where.append("e.folder = ?")
        params.append(folder)
    if label_id:
        label_row = db.fetch_one("SELECT * FROM mail_labels WHERE id = ?", (int(label_id),))
        if not label_row:
            return []
        where.append("""e.account_id = ? AND EXISTS (
            SELECT 1 FROM email_labels el
            WHERE el.email_id = e.id AND el.account_id = e.account_id AND el.label = ?
        )""")
        params.extend([label_row.get("account_id") or label_row.get("mailbox_id"), label_row.get("name")])
    elif label:
        where.append("""EXISTS (
            SELECT 1 FROM email_labels el
            WHERE el.email_id = e.id AND el.account_id = e.account_id AND el.label = ?
        )""")
        params.append(label)
    if cursor:
        where.append("e.id < ?")
        params.append(int(cursor))
        offset = 0
    else:
        offset = (max(int(page or 1), 1) - 1) * limit
    query = f"""
        SELECT e.*,
               a.id AS source_mailbox_id,
               a.provider AS account_provider,
               a.email AS account_email,
               COALESCE(a.display_name, a.email) AS account_display_name,
               a.status AS account_status
        FROM emails e
        JOIN accounts a ON a.id = e.account_id
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(e.date, e.created_at) DESC, e.id DESC
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])
    return [_public_email_row(row) for row in db.fetch_all(query, tuple(params))]


@router.get("/inbox")
async def get_inbox(
    mailbox_id: int = None,
    provider: str = None,
    folder_id: int = None,
    label_id: int = None,
    unread: Optional[bool] = None,
    limit: int = 50,
    cursor: int = None,
    page: int = None,
):
    db = get_db()
    emails = _with_email_attachments(_query_inbox_rows(
        db,
        limit=limit,
        mailbox_id=mailbox_id,
        provider=provider,
        folder_id=folder_id,
        label_id=label_id,
        unread=unread,
        cursor=cursor,
        page=page,
    ))
    return {"emails": emails, "count": len(emails), "mailbox_id": mailbox_id, "scope": "mailbox" if mailbox_id else "all"}


def _require_mailbox(db: Database, mailbox_id: int) -> dict:
    account = db.get_account_by_id(mailbox_id)
    if not account:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    if account.get("status") in {"paused", "disconnected"}:
        raise HTTPException(status_code=409, detail="Mailbox is not connected")
    return account


def _bucket_public(row: dict, mailbox: dict) -> dict:
    row = dict(row or {})
    row["mailbox_id"] = row.get("mailbox_id") or row.get("account_id") or mailbox.get("id")
    row["provider"] = row.get("provider") or mailbox.get("provider")
    row["email_address"] = row.get("email_address") or mailbox.get("email")
    row["synced_to_provider"] = bool(row.get("synced_to_provider"))
    row["created_locally"] = bool(row.get("created_locally"))
    return row


@router.get("/mailboxes/{mailbox_id}/folders")
async def get_mailbox_folders(mailbox_id: int):
    db = get_db()
    mailbox = _require_mailbox(db, mailbox_id)
    existing = db.get_all_folders(mailbox_id, include_shared=False)
    if not existing and mailbox.get("structure_sync_status") not in {"failed", "synced"}:
        try:
            ProviderMailboxTaxonomy(db).sync_mailbox_structure(mailbox_id)
        except Exception:
            logger.debug("Auto folder discovery failed for mailbox %s", mailbox_id, exc_info=True)
    folders = [_bucket_public(row, mailbox) for row in db.get_all_folders(mailbox_id, include_shared=False)]
    mailbox = db.get_account_by_id(mailbox_id) or mailbox
    return {"folders": folders, "count": len(folders), "mailbox": _mailbox_source(mailbox), "structure_status": mailbox.get("structure_sync_status")}


@router.post("/mailboxes/{mailbox_id}/folders")
async def create_mailbox_folder(mailbox_id: int, body: MailboxBucketCreateRequest):
    from backend.rules.action_executor import normalize_bucket_name

    db = get_db()
    mailbox = _require_mailbox(db, mailbox_id)
    name = normalize_bucket_name(body.name, "INBOX")
    remote = ProviderMailboxTaxonomy(db).create_remote_folder(mailbox, name)
    if "ok" not in remote and ("remote" in remote or "provider_id" in remote):
        remote["ok"] = True
    if not remote.get("ok") and not remote.get("unsupported"):
        raise HTTPException(status_code=502, detail=f"Could not create folder in provider account. Reason: {remote.get('message') or 'Provider error'}")
    folder_id = db.ensure_mail_folder(
        mailbox_id,
        name,
        {"source": "app_create", "provider_response": remote},
        provider_folder_id=remote.get("provider_id"),
        created_locally=True,
        synced_to_provider=bool(remote.get("remote")),
    )
    folder = db.fetch_one("SELECT * FROM mail_folders WHERE id = ?", (folder_id,))
    return {
        "status": "created",
        "message": f"Folder created in {mailbox['email']}" if remote.get("remote") else (remote.get("message") or f"Folder saved locally for {mailbox['email']}"),
        "folder": _bucket_public(folder, mailbox),
        "remote": remote,
    }


@router.get("/mailboxes/{mailbox_id}/labels")
async def get_mailbox_labels(mailbox_id: int):
    db = get_db()
    mailbox = _require_mailbox(db, mailbox_id)
    existing = db.get_all_labels(mailbox_id, include_shared=False)
    if not existing and mailbox.get("structure_sync_status") not in {"failed", "synced"}:
        try:
            ProviderMailboxTaxonomy(db).sync_mailbox_structure(mailbox_id)
        except Exception:
            logger.debug("Auto label discovery failed for mailbox %s", mailbox_id, exc_info=True)
    labels = [_bucket_public(row, mailbox) for row in db.get_all_labels(mailbox_id, include_shared=False)]
    mailbox = db.get_account_by_id(mailbox_id) or mailbox
    return {"labels": labels, "count": len(labels), "mailbox": _mailbox_source(mailbox), "structure_status": mailbox.get("structure_sync_status")}


@router.post("/mailboxes/{mailbox_id}/labels")
async def create_mailbox_label(mailbox_id: int, body: MailboxBucketCreateRequest):
    from backend.rules.action_executor import normalize_bucket_name

    db = get_db()
    mailbox = _require_mailbox(db, mailbox_id)
    name = normalize_bucket_name(body.name)
    remote = ProviderMailboxTaxonomy(db).create_remote_label(mailbox, name)
    if "ok" not in remote and ("remote" in remote or "provider_id" in remote):
        remote["ok"] = True
    if not remote.get("ok") and not remote.get("unsupported"):
        raise HTTPException(status_code=502, detail=f"Could not create label in provider account. Reason: {remote.get('message') or 'Provider error'}")
    label_id = db.ensure_mail_label(
        mailbox_id,
        name,
        provider_label_id=remote.get("provider_id"),
        created_locally=True,
        synced_to_provider=bool(remote.get("remote")),
    )
    if remote.get("folder_backed"):
        db.ensure_mail_folder(
            mailbox_id,
            remote.get("folder_name") or name,
            {"source": "app_label_create", "provider_response": remote},
            provider_folder_id=remote.get("provider_folder_id") or remote.get("provider_id"),
            created_locally=True,
            synced_to_provider=bool(remote.get("remote")),
            folder_path=remote.get("folder_name") or name,
        )
    label = db.fetch_one("SELECT * FROM mail_labels WHERE id = ?", (label_id,))
    return {
        "status": "created",
        "message": f"Label created in {mailbox['email']}" if remote.get("remote") else (remote.get("message") or "Label saved in the app; this provider did not expose a remote label endpoint."),
        "label": _bucket_public(label, mailbox),
        "remote": remote,
    }


@router.post("/mailboxes/{mailbox_id}/sync-structure")
async def sync_mailbox_structure(mailbox_id: int):
    db = get_db()
    mailbox = _require_mailbox(db, mailbox_id)
    result = ProviderMailboxTaxonomy(db).sync_mailbox_structure(mailbox_id)
    if not result.get("ok"):
        return {
            "status": "failed",
            "mailbox_id": mailbox_id,
            "provider": mailbox.get("provider"),
            "email_address": mailbox.get("email"),
            "message": result.get("message") or "Could not sync folders/labels for this mailbox. Retry.",
            "result": result,
        }
    return {
        "status": "synced",
        "mailbox_id": mailbox_id,
        "provider": mailbox.get("provider"),
        "email_address": mailbox.get("email"),
        "message": "Folders and labels synced.",
        **result,
    }


@router.post("/mailboxes/{mailbox_id}/sync")
async def sync_mailbox(mailbox_id: int, max_results: int = 50):
    db = get_db()
    mailbox = _require_mailbox(db, mailbox_id)
    sync_id = db.add_sync_status(mailbox_id, "pending")
    result = MailboxOrchestrator(db).sync_account(mailbox_id, max_results=max_results, sync_id=sync_id)
    status = "completed" if result.get("ok") else "failed"
    if not result.get("ok"):
        db.update_sync_status(sync_id, "failed", error=result.get("message") or result.get("status"))
    return {
        "status": status,
        "account_id": mailbox_id,
        "mailbox_id": mailbox_id,
        "provider": mailbox.get("provider"),
        "email_address": mailbox.get("email"),
        "sync_id": sync_id,
        "result": result,
    }


@router.post("/sync/all")
async def sync_all_mailboxes(max_results: int = 50):
    db = get_db()
    accounts = db.fetch_all("""
        SELECT * FROM accounts
        WHERE COALESCE(sync_enabled, 1) = 1
          AND COALESCE(status, 'connected') NOT IN ('paused', 'disconnected')
        ORDER BY id
    """)
    orchestrator = MailboxOrchestrator(db)
    jobs = []
    for account in accounts:
        sync_id = db.add_sync_status(account["id"], "pending")
        try:
            result = orchestrator.sync_account(account["id"], max_results=max_results, sync_id=sync_id)
            ok = bool(result.get("ok"))
            if not ok:
                db.update_sync_status(sync_id, "failed", error=result.get("message") or result.get("status"))
            jobs.append({
                "sync_id": sync_id,
                "account_id": account["id"],
                "mailbox_id": account["id"],
                "provider": account["provider"],
                "email_address": account["email"],
                "status": "completed" if ok else "failed",
                "result": result,
            })
        except Exception as exc:
            logger.exception("Mailbox sync failed for account %s during sync/all", account["id"])
            db.update_sync_status(sync_id, "failed", error=str(exc))
            jobs.append({
                "sync_id": sync_id,
                "account_id": account["id"],
                "mailbox_id": account["id"],
                "provider": account["provider"],
                "email_address": account["email"],
                "status": "failed",
                "result": {"ok": False, "status": "sync_failed", "message": str(exc)},
            })
    return {"status": "completed", "jobs": jobs, "count": len(jobs)}


@router.post("/accounts/remove")
async def remove_account_post(request_data: AccountRemoveRequest):
    db = get_db()
    account = db.get_account_by_id(request_data.account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.delete_account(request_data.account_id)
    return {"status": "success", "removed_account_id": request_data.account_id}


@router.delete("/accounts/{account_id}")
async def remove_account(account_id: int):
    return await remove_account_post(AccountRemoveRequest(account_id=account_id))


@router.put("/accounts/{account_id}")
async def update_account(account_id: int, body: AccountUpdateRequest):
    db = get_db()
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    meta_updates: dict = {}
    if body.imap_host is not None:
        meta_updates["imap_host"] = body.imap_host
    if body.imap_port is not None:
        meta_updates["imap_port"] = body.imap_port
    if body.smtp_host is not None:
        meta_updates["smtp_host"] = body.smtp_host
    if body.smtp_port is not None:
        meta_updates["smtp_port"] = body.smtp_port
    if body.sync_interval is not None:
        meta_updates["sync_interval"] = body.sync_interval
    if body.ssl is not None:
        sec = "ssl" if body.ssl else "starttls"
        meta_updates["security"] = sec
        meta_updates["smtp_security"] = sec
    if body.security is not None:
        meta_updates["security"] = body.security
        meta_updates["smtp_security"] = body.security

    if meta_updates:
        db.update_account_metadata(account_id, meta_updates)

    if body.password:
        from backend.auth.token_crypto import TokenCipher
        encrypted = TokenCipher().encrypt(body.password)
        db.execute(
            "UPDATE accounts SET refresh_token = ?, updated_at = ? WHERE id = ?",
            (encrypted, datetime.now().isoformat(), account_id),
        )

    return {"status": "updated", "account": public_account(db.get_account_by_id(account_id))}


@router.post("/accounts/{account_id}/sync")
async def sync_one_account(account_id: int, request: Request, background_tasks: BackgroundTasks):
    account = get_db().get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return await start_sync(request, background_tasks, account_id=account_id)


@router.post("/accounts/{account_id}/reconnect")
async def reconnect_account(account_id: int, request: Request, body: AccountReconnectRequest = Body(default=None)):
    db = get_db()
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    provider = ProviderCapabilityRegistry.normalize(account["provider"])
    auth_type = (account.get("auth_type") or "").lower()

    # OAuth accounts — delegate to the respective OAuth start handler
    from backend.auth.routes import (
        google_start as _g_start,
        microsoft_start as _ms_start,
        yahoo_start as _y_start,
        zoho_start as _zo_start,
        yandex_start as _ya_start,
        OAuthStartBody as _OAuthBody,
    )
    if provider == "gmail":
        return await _g_start(request, _OAuthBody(email=account.get("email")))
    if provider in ("outlook", "microsoft365", "exchange"):
        return await _ms_start(request, _OAuthBody(email=account.get("email")))
    if provider == "yahoo" and auth_type.startswith("oauth"):
        return await _y_start(request, _OAuthBody(email=account.get("email")))
    if provider == "zoho" and auth_type.startswith("oauth"):
        return await _zo_start(request, _OAuthBody(email=account.get("email")))
    if provider == "yandex" and auth_type.startswith("oauth"):
        return await _ya_start(request, _OAuthBody(email=account.get("email")))

    # Manual/IMAP accounts — credential-based reconnect
    result = MailboxOrchestrator(db).reconnect(
        account_id,
        password=(body.password if body else None),
        host=(body.host if body else None),
        port=(body.port if body else None),
        security=(body.security if body else None),
    )
    if not result.get("ok") and result.get("status") != "credential_required":
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/accounts/{account_id}/pause")
async def pause_account(account_id: int):
    db = get_db()
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.update_account_status(account_id, "paused", "paused")
    return {"status": "success", "message": f"Sync paused for {account_id}", "provider": account["provider"]}


@router.post("/accounts/{account_id}/resume")
async def resume_account(account_id: int):
    db = get_db()
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    db.update_account_status(account_id, "connected", "active")
    return {"status": "success", "message": f"Sync resumed for {account_id}", "provider": account["provider"]}


@router.get("/accounts/{account_id}/diagnostics")
async def account_diagnostics(account_id: int):
    db = get_db()
    account = db.get_account_by_id(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    diagnostic = db.get_latest_provider_diagnostic(account_id)
    return {
        "account": public_account(account),
        "diagnostic": diagnostic,
        "token_present": bool(account.get("access_token") or account.get("refresh_token")),
        "status": account.get("status") or "connected",
        "reconnect_state": account.get("reconnect_state") or "ok",
    }


# Sync Endpoints
@router.post("/sync/start")
async def start_sync(request: Request, background_tasks: BackgroundTasks, account_id: int = None):
    db = get_db()
    payload = {}
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            payload = await request.json()
    except Exception:
        payload = {}

    sync_request = SyncStartRequest(
        account_id=payload.get("account_id", account_id),
        provider=payload.get("provider"),
        max_results=payload.get("max_results", 50),
    )

    if sync_request.account_id:
        account = db.get_account_by_id(sync_request.account_id)
        accounts = [account] if account else []
    elif sync_request.provider:
        accounts = db.fetch_all("SELECT * FROM accounts WHERE provider = ?", (sync_request.provider,))
    else:
        accounts = db.get_all_accounts()

    if not accounts:
        raise HTTPException(status_code=404, detail="No connected accounts found")

    jobs = []
    enterprise_system = getattr(request.app.state, "enterprise_system", None)
    orchestrator = MailboxOrchestrator(db)
    for account in accounts:
        sync_id = db.add_sync_status(account["id"], "pending")
        validation = orchestrator.validate_account(account["id"], "sync")
        if not validation.get("ok"):
            db.update_sync_status(sync_id, "failed", error=validation.get("message") or validation.get("status"))
            db.add_provider_diagnostic(account["id"], account["provider"], validation.get("status", "sync_rejected"), validation)
            jobs.append({
                "sync_id": sync_id,
                "account_id": account["id"],
                "provider": account["provider"],
                "status": "failed",
                "reason": validation.get("status"),
            })
            continue
        if enterprise_system:
            ready = enterprise_system.queue_provider_sync(
                account["id"],
                account["provider"],
                sync_request.max_results,
                sync_id,
                metadata={"endpoint": "/sync/start", "account_id": account["id"]}
            )
            if ready:
                jobs.append({"sync_id": sync_id, "account_id": account["id"], "provider": account["provider"], "status": "queued"})
                continue
            logger.warning(f"Enterprise system queue busy for provider {account['provider']}, falling back to background task")

        background_tasks.add_task(provider_sync_task, account["id"], account["provider"], sync_request.max_results, sync_id)
        jobs.append({"sync_id": sync_id, "account_id": account["id"], "provider": account["provider"], "status": "pending"})

    return {"status": "started", "jobs": jobs, "message": "Email sync started"}


@router.get("/sync/status")
async def get_sync_status(account_id: int = None):
    db = get_db()
    if account_id:
        syncs = db.fetch_all(
            "SELECT * FROM sync_status WHERE account_id = ? ORDER BY started_at DESC LIMIT 5",
            (account_id,)
        )
    else:
        syncs = db.fetch_all("SELECT * FROM sync_status ORDER BY started_at DESC LIMIT 20")

    latest = syncs[0] if syncs else None
    active = [sync for sync in syncs if sync["status"] in ("pending", "in_progress")]
    aggregate_status = active[0]["status"] if active else (latest["status"] if latest else "idle")
    progress = max([sync.get("progress") or 0 for sync in active], default=(latest.get("progress") if latest else 0))
    latest_diagnostic = None
    if latest:
        latest_diagnostic = db.get_latest_provider_diagnostic(latest["account_id"])
    return {
        "status": aggregate_status,
        "progress": progress or 0,
        "syncs": syncs,
        "active": active,
        "latest": latest,
        "latest_diagnostic": latest_diagnostic,
        "last_error": latest.get("last_error") if latest else None,
        "timestamp": datetime.now().isoformat(),
    }


# Email Endpoints
@router.get("/emails")
async def get_emails(
    limit: int = 50,
    category: str = None,
    folder: str = None,
    label: str = None,
    mailbox_id: int = None,
    provider: str = None,
    folder_id: int = None,
    label_id: int = None,
    unread: Optional[bool] = None,
):
    db = get_db()
    emails = _with_email_attachments(_query_inbox_rows(
        db,
        limit=limit,
        mailbox_id=mailbox_id,
        provider=provider,
        folder_id=folder_id,
        label_id=label_id,
        unread=unread,
        category=category,
        folder=folder,
        label=label,
    ))
    return {"emails": emails, "count": len(emails)}


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: str, _auth=Depends(require_local_auth)):
    meta = attachment_storage.get_metadata(attachment_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Attachment not found")
    data = attachment_storage.retrieve(attachment_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Attachment data not found")
    # Strip CRLF and quotes from filename to prevent HTTP header injection
    raw_name = (meta.filename or "attachment").replace("\r", "").replace("\n", "").replace('"', "")
    quoted = quote(raw_name)
    # Use only RFC 5987 encoded form; omit bare filename="" to avoid injection vectors
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}
    content_type = (meta.content_type or "application/octet-stream").replace("\r", "").replace("\n", "")
    return StreamingResponse(iter([data]), media_type=content_type, headers=headers)


@router.delete("/emails")
async def clear_emails():
    db = get_db()
    # Safety rule: never permanently delete provider emails automatically.
    # This endpoint now soft-deletes local rows so Restore Center/recovery can
    # bring them back and sync corruption cannot wipe mail accidentally.
    snapshot = {"reason": "manual_clear", "at": datetime.now().isoformat()}
    db.execute("UPDATE emails SET delete_state = 'deleted', deleted_at = ?, restore_snapshot = ? WHERE COALESCE(delete_state, 'active') != 'deleted'", (snapshot["at"], json.dumps(snapshot, sort_keys=True)))
    return {"status": "soft_deleted", "message": "Emails moved to local restore center. No provider email was permanently deleted."}


@router.post("/emails/restore")
async def restore_emails():
    db = get_db()
    db.execute("UPDATE emails SET delete_state = 'active', deleted_at = NULL WHERE delete_state = 'deleted'")
    return {"status": "restored", "message": "Soft-deleted local emails restored."}


# Settings Endpoints
def default_local_settings() -> dict:
    return {
        "auto_classify": True,
        "show_suggestions": True,
        "notifications": False,
        "auto_sync": True,
        "background_sync_interval_seconds": get_sync_interval_seconds(),
        "confidence_threshold": 0.95,
    }


@router.get("/settings")
async def get_settings():
    db = get_db()
    defaults = default_local_settings()
    user = db.fetch_one("SELECT settings FROM users WHERE email = ? ORDER BY id LIMIT 1", ("local@aiemailorganizer.local",))
    if user and user.get("settings"):
        try:
            defaults.update(json.loads(user["settings"]))
        except (TypeError, json.JSONDecodeError):
            pass
    defaults["background_sync_interval_seconds"] = int(defaults.get("background_sync_interval_seconds") or get_sync_interval_seconds())
    return {"settings": defaults, "allowed_sync_intervals": [20, 30, 60]}


def normalize_settings_payload(settings: dict) -> dict:
    payload = dict(settings or {})
    # Frontend forms use human-readable names; normalize them to persisted runtime keys.
    if "sync_interval" in payload and "background_sync_interval_seconds" not in payload:
        payload["background_sync_interval_seconds"] = payload.pop("sync_interval")
    if "confidence" in payload and "confidence_threshold" not in payload:
        try:
            payload["confidence_threshold"] = max(0.0, min(1.0, float(payload.pop("confidence")) / 100.0))
        except (TypeError, ValueError):
            payload.pop("confidence", None)
    for key in ("preserve_accounts", "manual_delete_only", "attachments", "corrections"):
        if key in payload:
            payload[key] = str(payload[key]).lower() not in {"", "0", "false", "off", "none"}
    return payload


@router.put("/settings")
async def update_settings(settings: dict):
    db = get_db()
    merged = default_local_settings()
    merged.update(normalize_settings_payload(settings))
    try:
        interval = int(merged.get("background_sync_interval_seconds") or 30)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="background_sync_interval_seconds must be numeric")
    if interval not in (20, 30, 60):
        raise HTTPException(status_code=400, detail="background_sync_interval_seconds must be one of 20, 30, or 60")
    merged["background_sync_interval_seconds"] = set_sync_interval(interval)
    merged["auto_sync"] = set_sync_enabled(bool(merged.get("auto_sync", True)))
    merged["accounts_manual_delete_only"] = bool(merged.get("manual_delete_only", True))
    merged["preserve_accounts"] = bool(merged.get("preserve_accounts", True))
    user_id = db.add_user("local@aiemailorganizer.local", "local", merged)
    db.execute("UPDATE users SET settings = ? WHERE id = ?", (json.dumps(merged, sort_keys=True), user_id))
    return {"status": "success", "settings": merged}


@router.get("/metrics")
async def get_metrics():
    db = get_db()
    confidence = db.fetch_one("SELECT AVG(confidence) as avg_confidence FROM emails WHERE confidence IS NOT NULL")
    avg_confidence = round((confidence.get("avg_confidence") or 0) * 100, 1) if confidence else 0
    feedback_count = db.get_feedback_count()
    return {
        "total_classifications": len(db.fetch_all("SELECT * FROM emails")),
        "avg_confidence": avg_confidence,
        "total_feedback": feedback_count["count"] if feedback_count else 0,
        "total_rules_triggered": len(db.fetch_all("SELECT * FROM rules WHERE is_active = 1"))
    }


@router.get("/health/detailed")
async def health_detailed():
    import psutil
    db = get_db()
    db_status = db.get_connection_status()
    return {
        "status": "healthy",
        "system": {
            "cpu": {"usage_percent": psutil.cpu_percent()},
            "memory": {"used_gb": psutil.virtual_memory().used / (1024 ** 3)}
        },
        "database": db_status
    }


# Realtime SSE Endpoint
async def event_generator():
    while True:
        db = get_db()
        syncs = db.fetch_all("SELECT * FROM sync_status ORDER BY started_at DESC LIMIT 5")
        email_count = (db.fetch_one("SELECT COUNT(*) AS c FROM emails WHERE created_at > datetime('now', '-1 hour')") or {}).get("c", 0)
        accounts = [public_account(account) for account in db.get_all_accounts()]
        data = {
            "sync_status": syncs,
            "new_emails": email_count,
            "accounts": accounts,
            "timestamp": datetime.now().isoformat()
        }
        yield f"data: {json.dumps(data)}\n\n"
        await asyncio.sleep(2)


@router.get("/events")
async def stream_events():
    return StreamingResponse(event_generator(), media_type="text/event-stream")
