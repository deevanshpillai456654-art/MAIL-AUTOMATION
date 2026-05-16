from __future__ import annotations
from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel
from typing import Optional, Any, Dict
import json
from backend.db.database import Database
from backend.core.account_persistence import detect_mail_settings, account_metadata
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.auth.provider_config import ProviderConfigManager, oauth_group_for
from backend.auth.token_crypto import TokenCipher
from backend import config

router = APIRouter()
db = Database(config.DB_PATH)

MANUAL_METHODS = {"app_password", "imap", "imap_smtp", "advanced_imap", "manual", "password"}
OAUTH_METHODS = {"oauth", "oauth2", "provider_oauth"}


class EnterpriseAccountPayload(BaseModel):
    email: str
    provider: str = "custom"
    auth_type: Optional[str] = None
    connection_method: Optional[str] = None
    oauth_provider: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expiry: Optional[str] = None
    token_scopes: Optional[list[str] | str] = None
    password: Optional[str] = None
    app_password: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: int = 993
    smtp_host: Optional[str] = None
    smtp_port: int = 465
    ssl: bool = True
    sync_interval: int = 20


@router.post("/enterprise/accounts/detect")
async def enterprise_detect_account(payload: Dict[str, Any] = Body(default_factory=dict)):
    email = str(payload.get("email") or "")
    detected = detect_mail_settings(email)
    provider = ProviderCapabilityRegistry.normalize(str(payload.get("provider") or detected.get("provider") or "custom"))
    capability = ProviderCapabilityRegistry().get(provider)
    group = oauth_group_for(provider)
    oauth_status = ProviderConfigManager().status(group) if group else None
    return {
        **detected,
        "capabilities": capability.as_dict(),
        "connection_method": "oauth" if group else ("advanced_imap" if capability.requires_host else "app_password"),
        "oauth_provider": group,
        "requires_password": False if group else True,
        "password_required": False if group else True,
        "oauth_status": oauth_status,
    }


@router.post("/enterprise/accounts/save")
async def enterprise_save_account(payload: EnterpriseAccountPayload):
    detected = detect_mail_settings(payload.email)
    provider = ProviderCapabilityRegistry.normalize(payload.provider or detected.get("provider") or "custom")
    capability = ProviderCapabilityRegistry().get(provider)
    oauth_group = oauth_group_for(payload.oauth_provider or provider)
    method = (payload.connection_method or payload.auth_type or ("oauth" if oauth_group else "app_password")).strip().lower()
    password = payload.password or payload.app_password

    if method in OAUTH_METHODS or oauth_group:
        group = oauth_group or ProviderCapabilityRegistry.normalize(payload.oauth_provider or provider)
        if not payload.access_token:
            status = ProviderConfigManager().status(group)
            raise HTTPException(status_code=428, detail={
                "status": "oauth_required",
                "message": "Use the provider OAuth redirect/callback flow. OAuth account save never accepts or requires mailbox passwords.",
                "provider": provider,
                "oauth_provider": group,
                "oauth_start_url": {"gmail":"/api/v1/oauth/google/start","microsoft":"/api/v1/oauth/microsoft/start","yahoo":"/api/v1/oauth/yahoo/start","zoho":"/api/v1/oauth/zoho/start"}.get(group, "/api/v1/accounts/detect"),
                "password_required": False,
                "app_password_required": False,
                "configuration": status,
            })
        metadata = account_metadata(
            payload.sync_interval,
            auth_type="oauth",
            oauth_provider=group,
            token_scopes=payload.token_scopes or sorted(capability.protocols),
            provider_capabilities=capability.as_dict(),
            password_required=False,
            app_password_required=False,
            validate_oauth_tokens_only=True,
        )
        account_id = db.upsert_account(
            user_id=db.add_user(payload.email.lower(), provider),
            email=payload.email,
            provider=provider,
            access_token=TokenCipher().encrypt(payload.access_token),
            refresh_token=TokenCipher().encrypt(payload.refresh_token) if payload.refresh_token else None,
            token_expiry=payload.token_expiry,
            status="connected",
            reconnect_state="ok",
            metadata=metadata,
            auth_type="oauth",
            oauth_provider=group,
            token_scopes=json.dumps(payload.token_scopes or sorted(capability.protocols)),
            sync_status="pending",
            webhook_enabled=1 if capability.supports_watch else 0,
            provider_capabilities=json.dumps(capability.as_dict(), sort_keys=True),
        )
        db.add_provider_diagnostic(account_id, provider, "oauth_saved", {"ok": True, "password_required": False})
        db.add_sync_status(account_id, "pending")
        return {"status": "saved", "account_id": account_id, "auth_type": "oauth", "password_required": False, "account": {"id": account_id, "email": payload.email, "provider": provider, "metadata": metadata}}

    if method in MANUAL_METHODS and not password:
        raise HTTPException(status_code=400, detail={
            "status": "credential_required",
            "message": "Manual IMAP/SMTP providers require an app password or mailbox password.",
            "provider": provider,
            "auth_type": "manual",
            "password_required": True,
        })

    user_id = db.add_user(payload.email.lower(), provider)
    metadata = account_metadata(
        payload.sync_interval,
        auth_type="manual",
        credential_storage="encrypted_local_vault",
        imap_host=payload.imap_host or detected.get("imap_host") or capability.default_imap_host,
        imap_port=payload.imap_port or detected.get("imap_port") or capability.default_imap_port,
        smtp_host=payload.smtp_host or detected.get("smtp_host") or capability.default_smtp_host,
        smtp_port=payload.smtp_port or detected.get("smtp_port") or capability.default_smtp_port,
        ssl=payload.ssl,
        account_editable=True,
        provider_capabilities=capability.as_dict(),
    )
    account_id = db.upsert_account(
        user_id=user_id,
        email=payload.email,
        provider=provider,
        refresh_token=TokenCipher().encrypt(password) if password else None,
        status="connected",
        reconnect_state="ok",
        metadata=metadata,
        auth_type="manual",
        sync_status="pending",
        webhook_enabled=0,
        provider_capabilities=json.dumps(capability.as_dict(), sort_keys=True),
    )
    db.add_sync_status(account_id, "pending")
    return {"status":"saved", "account_id": account_id, "auth_type": "manual", "account": {"id":account_id, "email":payload.email, "provider":provider, "metadata":metadata}}


@router.get("/enterprise/accounts/status")
async def enterprise_accounts_status():
    accounts = db.get_all_accounts()
    return {"status":"ready", "count":len(accounts), "accounts":accounts, "persistence":"manual_removal_only"}
