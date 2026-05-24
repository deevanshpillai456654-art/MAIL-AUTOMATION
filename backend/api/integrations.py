"""
Extended API routes for Gmail and Outlook integrations
"""


import re as _re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from backend.auth.local_auth import require_local_auth

_AUTH = [Depends(require_local_auth)]
import json

import requests

from backend import config
from backend.auth.gmail_auth import GmailOAuth
from backend.auth.outlook_auth import OutlookOAuth
from backend.db.database import Database

router = APIRouter()
db = Database(config.DB_PATH)


class GmailAccountInput(BaseModel):
    email: str
    user_id: int


class OutlookAccountInput(BaseModel):
    email: str
    user_id: int
    tenant_id: Optional[str] = None


class GmailLabelInput(BaseModel):
    email: str
    label_name: str
    message_id: str

    @field_validator('message_id')
    @classmethod
    def _validate_message_id(cls, v: str) -> str:
        if not v or len(v) > 512 or not _re.match(r'^[A-Za-z0-9_\-=]+$', v):
            raise ValueError('message_id contains invalid characters')
        return v


class OutlookFolderInput(BaseModel):
    email: str
    folder_name: str
    message_id: str

    @field_validator('message_id')
    @classmethod
    def _validate_message_id(cls, v: str) -> str:
        if not v or len(v) > 512 or not _re.match(r'^[A-Za-z0-9_\-=]+$', v):
            raise ValueError('message_id contains invalid characters')
        return v


class SyncStatusResponse(BaseModel):
    provider: str
    email: str
    last_sync: str
    status: str
    emails_processed: int


@router.post("/accounts/gmail")
async def add_gmail_account(account: GmailAccountInput):
    raise HTTPException(status_code=400, detail="Connect Gmail through /api/oauth/google/start so OAuth tokens are stored securely")


@router.post("/accounts/outlook")
async def add_outlook_account(account: OutlookAccountInput):
    raise HTTPException(status_code=400, detail="Connect Outlook through /api/oauth/microsoft/start so OAuth tokens are stored securely")


@router.post("/gmail/label", dependencies=_AUTH)
async def apply_gmail_label(label_input: GmailLabelInput):
    account = db.get_account_by_email(label_input.email)
    if not account or account["provider"] != "gmail":
        raise HTTPException(status_code=404, detail="Connected Gmail account not found")

    token = GmailOAuth(db=db, email_address=account.get("email")).get_valid_token(account["id"])
    if not token:
        raise HTTPException(status_code=401, detail="Gmail account needs reconnect")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    labels_response = requests.get("https://gmail.googleapis.com/gmail/v1/users/me/labels", headers=headers, timeout=20)
    if not labels_response.ok:
        raise HTTPException(status_code=labels_response.status_code, detail=labels_response.text)

    labels = labels_response.json().get("labels", [])
    label = next((item for item in labels if item.get("name", "").lower() == label_input.label_name.lower()), None)
    if not label:
        create_response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/labels",
            headers=headers,
            json={"name": label_input.label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            timeout=20,
        )
        if not create_response.ok:
            raise HTTPException(status_code=create_response.status_code, detail=create_response.text)
        label = create_response.json()

    modify_response = requests.post(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{label_input.message_id}/modify",
        headers=headers,
        json={"addLabelIds": [label["id"]]},
        timeout=20,
    )
    if not modify_response.ok:
        raise HTTPException(status_code=modify_response.status_code, detail=modify_response.text)

    return {"status": "success", "provider": "gmail", "label": label, "message_id": label_input.message_id}


@router.get("/gmail/labels/{email}", dependencies=_AUTH)
async def get_gmail_labels(email: str):
    account = db.get_account_by_email(email)
    if not account or account["provider"] != "gmail":
        raise HTTPException(status_code=404, detail="Connected Gmail account not found")
    token = GmailOAuth(db=db, email_address=account.get("email")).get_valid_token(account["id"])
    if not token:
        raise HTTPException(status_code=401, detail="Gmail account needs reconnect")
    response = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/labels",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if not response.ok:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return {"labels": response.json().get("labels", [])}


@router.post("/outlook/folder", dependencies=_AUTH)
async def move_to_outlook_folder(folder_input: OutlookFolderInput):
    account = db.get_account_by_email(folder_input.email)
    if not account or account["provider"] != "outlook":
        raise HTTPException(status_code=404, detail="Connected Outlook account not found")

    token = OutlookOAuth(db=db, email_address=account.get("email")).get_valid_token(account["id"])
    if not token:
        raise HTTPException(status_code=401, detail="Outlook account needs reconnect")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    folders_response = requests.get("https://graph.microsoft.com/v1.0/me/mailFolders?$top=100", headers=headers, timeout=20)
    if not folders_response.ok:
        raise HTTPException(status_code=folders_response.status_code, detail=folders_response.text)

    folders = folders_response.json().get("value", [])
    folder = next((item for item in folders if item.get("displayName", "").lower() == folder_input.folder_name.lower()), None)
    if not folder:
        create_response = requests.post(
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/childFolders",
            headers=headers,
            json={"displayName": folder_input.folder_name},
            timeout=20,
        )
        if not create_response.ok:
            raise HTTPException(status_code=create_response.status_code, detail=create_response.text)
        folder = create_response.json()

    move_response = requests.post(
        f"https://graph.microsoft.com/v1.0/me/messages/{folder_input.message_id}/move",
        headers=headers,
        json={"destinationId": folder["id"]},
        timeout=20,
    )
    if not move_response.ok:
        raise HTTPException(status_code=move_response.status_code, detail=move_response.text)

    return {"status": "success", "provider": "outlook", "folder": folder, "message": move_response.json()}


@router.get("/outlook/folders/{email}", dependencies=_AUTH)
async def get_outlook_folders(email: str):
    account = db.get_account_by_email(email)
    if not account or account["provider"] != "outlook":
        raise HTTPException(status_code=404, detail="Connected Outlook account not found")
    token = OutlookOAuth(db=db, email_address=account.get("email")).get_valid_token(account["id"])
    if not token:
        raise HTTPException(status_code=401, detail="Outlook account needs reconnect")
    response = requests.get(
        "https://graph.microsoft.com/v1.0/me/mailFolders?$top=100",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    if not response.ok:
        raise HTTPException(status_code=response.status_code, detail=response.text)
    return {"folders": response.json().get("value", [])}


@router.get("/sync/status/{provider}", dependencies=_AUTH)
async def get_sync_status(provider: str, email: str):
    account = db.fetch_one("SELECT * FROM accounts WHERE provider = ? AND email = ?", (provider, email))
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    latest = db.fetch_one(
        "SELECT * FROM sync_status WHERE account_id = ? ORDER BY started_at DESC LIMIT 1",
        (account["id"],)
    )
    return SyncStatusResponse(
        provider=provider,
        email=email,
        last_sync=account.get("last_sync_at") or (latest.get("completed_at") if latest else ""),
        status=latest["status"] if latest else "idle",
        emails_processed=latest["processed_emails"] if latest else 0
    )


@router.post("/sync/stop", dependencies=_AUTH)
async def stop_sync(email: str):
    account = db.get_account_by_email(email)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    active = db.get_active_sync(account["id"])
    if active:
        db.update_sync_status(active["id"], "cancelled")
        return {"status": "cancelled", "sync_id": active["id"]}
    return {"status": "idle"}


@router.get("/settings/{user_id}", dependencies=_AUTH)
async def get_user_settings(user_id: int):
    user = db.fetch_one("SELECT settings FROM users WHERE id = ?", (user_id,))
    if user and user.get("settings"):
        try:
            settings = json.loads(user["settings"])
        except (json.JSONDecodeError, TypeError):
            settings = {}
    else:
        settings = {
            "auto_classify": True,
            "show_suggestions": True,
            "notifications": False,
            "dark_mode": False,
            "confidence_threshold": 0.70
        }

    return {"settings": settings}


@router.put("/settings/{user_id}", dependencies=_AUTH)
async def update_user_settings(user_id: int, settings: dict):
    db.execute(
        "UPDATE users SET settings = ? WHERE id = ?",
        (json.dumps(settings), user_id)
    )
    return {"status": "success", "message": "Settings updated"}


@router.get("/stats/{user_id}", dependencies=_AUTH)
async def get_user_stats(user_id: int):
    stats = db.fetch_one("""
        SELECT
            COUNT(DISTINCT a.id) as total_accounts,
            COUNT(DISTINCT e.id) as total_emails,
            COUNT(DISTINCT e.category) as categories_used,
            COUNT(DISTINCT f.id) as total_feedback
        FROM accounts a
        LEFT JOIN emails e ON a.id = e.account_id
        LEFT JOIN feedback f ON f.user_id = a.user_id
        WHERE a.user_id = ?
    """, (user_id,))

    return {
        "accounts": stats["total_accounts"] if stats else 0,
        "emails": stats["total_emails"] if stats else 0,
        "categories": stats["categories_used"] if stats else 0,
        "corrections": stats["total_feedback"] if stats else 0
    }


@router.get("/gmail/status", dependencies=_AUTH)
async def gmail_status():
    accounts = db.fetch_all("SELECT * FROM accounts WHERE provider = 'gmail'")
    return {
        "provider": "gmail",
        "connected": len(accounts) > 0,
        "accounts": len(accounts),
        "last_sync": max([a.get("last_sync_at") or "" for a in accounts], default="")
    }


@router.get("/outlook/status", dependencies=_AUTH)
async def outlook_status():
    accounts = db.fetch_all("SELECT * FROM accounts WHERE provider = 'outlook'")
    return {
        "provider": "outlook",
        "connected": len(accounts) > 0,
        "accounts": len(accounts),
        "last_sync": max([a.get("last_sync_at") or "" for a in accounts], default="")
    }


@router.get("/imap/status", dependencies=_AUTH)
async def imap_status():
    accounts = db.fetch_all("SELECT * FROM accounts WHERE provider IN ('imap', 'yahoo', 'zoho')")
    return {
        "provider": "imap",
        "connected": len(accounts) > 0,
        "accounts": len(accounts),
        "last_sync": max([a.get("last_sync_at") or "" for a in accounts], default="")
    }
