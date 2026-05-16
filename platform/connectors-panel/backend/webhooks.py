"""
Webhooks router — manage webhook endpoints and receive inbound webhooks.
Prefix: /webhooks

Webhook secrets are NEVER exposed in API responses.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from .db import get_panel_db
from .models import (
    APIResponse,
    WebhookCreateRequest,
    WebhookEndpointSafe,
)
from ..shared.utils import (
    compute_hmac,
    decrypt_secret,
    encrypt_secret,
    generate_webhook_id,
    generate_webhook_secret,
    utc_now_str,
    verify_hmac,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_safe_webhook(row: dict[str, Any]) -> WebhookEndpointSafe:
    events_raw = row.get("events_json", "[]")
    if isinstance(events_raw, str):
        try:
            events = json.loads(events_raw)
        except Exception:
            events = []
    else:
        events = events_raw or []

    return WebhookEndpointSafe(
        webhook_id=row["id"],
        connector_id=row["connector_id"],
        tenant_id=row["tenant_id"],
        url=row["url"],
        events=events,
        is_active=bool(row.get("is_active", 1)),
        created_at=datetime.fromisoformat(row["created_at"]),
        last_triggered=datetime.fromisoformat(row["last_triggered"]) if row.get("last_triggered") else None,
        failure_count=row.get("failure_count", 0),
        success_count=row.get("success_count", 0),
    )


def _require_webhook(webhook_id: str) -> dict[str, Any]:
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM webhooks WHERE id = ?", (webhook_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Webhook '{webhook_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[WebhookEndpointSafe], summary="List webhooks for tenant")
async def list_webhooks(
    tenant_id: str = Query(...),
    connector_id: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
):
    db = get_panel_db()
    sql = "SELECT * FROM webhooks WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]
    if connector_id:
        sql += " AND connector_id = ?"
        params.append(connector_id)
    if is_active is not None:
        sql += " AND is_active = ?"
        params.append(1 if is_active else 0)
    sql += " ORDER BY created_at DESC"
    rows = db.fetch_all(sql, params)
    return [_row_to_safe_webhook(r) for r in rows]


@router.post(
    "",
    response_model=WebhookEndpointSafe,
    status_code=status.HTTP_201_CREATED,
    summary="Create webhook endpoint",
)
async def create_webhook(body: WebhookCreateRequest):
    db = get_panel_db()
    webhook_id = generate_webhook_id()
    now = utc_now_str()

    secret = body.secret or generate_webhook_secret()
    secret_enc = encrypt_secret(secret)

    db.execute(
        """
        INSERT INTO webhooks
            (id, connector_id, tenant_id, url, secret_enc, events_json,
             is_active, created_at, last_triggered, failure_count, success_count)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL, 0, 0)
        """,
        (
            webhook_id,
            body.connector_id,
            body.tenant_id,
            body.url,
            secret_enc,
            json.dumps(body.events),
            now,
        ),
    )

    return WebhookEndpointSafe(
        webhook_id=webhook_id,
        connector_id=body.connector_id,
        tenant_id=body.tenant_id,
        url=body.url,
        events=body.events,
        is_active=True,
        created_at=datetime.fromisoformat(now),
    )


@router.get("/{webhook_id}", response_model=WebhookEndpointSafe, summary="Get webhook details")
async def get_webhook(webhook_id: str):
    row = _require_webhook(webhook_id)
    return _row_to_safe_webhook(row)


@router.put("/{webhook_id}", response_model=WebhookEndpointSafe, summary="Update webhook")
async def update_webhook(
    webhook_id: str,
    url: Optional[str] = None,
    events: Optional[list[str]] = None,
    is_active: Optional[bool] = None,
    tenant_id: str = Query(...),
):
    row = _require_webhook(webhook_id)
    if row["tenant_id"] != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    db = get_panel_db()
    updates: list[str] = []
    params: list[Any] = []

    if url is not None:
        updates.append("url = ?")
        params.append(url)
    if events is not None:
        updates.append("events_json = ?")
        params.append(json.dumps(events))
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)

    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No fields to update")

    params.append(webhook_id)
    db.execute(f"UPDATE webhooks SET {', '.join(updates)} WHERE id = ?", params)
    return _row_to_safe_webhook(_require_webhook(webhook_id))


@router.delete("/{webhook_id}", response_model=APIResponse, summary="Delete webhook")
async def delete_webhook(webhook_id: str, tenant_id: str = Query(...)):
    row = _require_webhook(webhook_id)
    if row["tenant_id"] != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    db = get_panel_db()
    db.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
    return APIResponse(message=f"Webhook '{webhook_id}' deleted")


@router.post("/{webhook_id}/test", response_model=APIResponse, summary="Send test event to webhook")
async def test_webhook(webhook_id: str, tenant_id: str = Query(...)):
    row = _require_webhook(webhook_id)
    if row["tenant_id"] != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    # Build test payload
    test_payload = json.dumps({
        "event": "webhook.test",
        "webhook_id": webhook_id,
        "timestamp": utc_now_str(),
        "message": "This is a test delivery from MailPilot",
    }).encode()

    # Sign the payload
    secret_enc = row.get("secret_enc")
    signature = ""
    if secret_enc:
        try:
            secret = decrypt_secret(secret_enc)
            signature = compute_hmac(secret, test_payload)
        except Exception:
            pass

    # Deliver
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                row["url"],
                content=test_payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Hub-Signature-256": signature,
                    "X-MailPilot-Event": "webhook.test",
                },
            )
        success = response.is_success
        detail = f"HTTP {response.status_code}"
    except Exception as exc:
        success = False
        detail = str(exc)

    db = get_panel_db()
    if success:
        db.execute(
            "UPDATE webhooks SET success_count = success_count + 1, last_triggered = ? WHERE id = ?",
            (utc_now_str(), webhook_id),
        )
    else:
        db.execute(
            "UPDATE webhooks SET failure_count = failure_count + 1, last_triggered = ? WHERE id = ?",
            (utc_now_str(), webhook_id),
        )

    return APIResponse(
        success=success,
        message=f"Test delivery {'succeeded' if success else 'failed'}: {detail}",
    )


@router.get("/{webhook_id}/logs", summary="Get webhook delivery logs (last 100)")
async def get_webhook_logs(webhook_id: str, tenant_id: str = Query(...)):
    row = _require_webhook(webhook_id)
    if row["tenant_id"] != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    db = get_panel_db()
    logs = db.fetch_all(
        """
        SELECT * FROM connector_logs
        WHERE connector_id = ? AND tenant_id = ?
          AND message LIKE '%webhook%'
        ORDER BY timestamp DESC LIMIT 100
        """,
        (row["connector_id"], tenant_id),
    )
    return {"webhook_id": webhook_id, "logs": logs, "count": len(logs)}


@router.post("/receive/{connector_id}", summary="Receive inbound webhook (validates HMAC signature)")
async def receive_webhook(
    connector_id: str,
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    x_webhook_event: Optional[str] = Header(None, alias="X-Webhook-Event"),
    tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
):
    body_bytes = await request.body()

    db = get_panel_db()

    # Find active webhook for this connector
    query_params: list[Any] = [connector_id]
    sql = "SELECT * FROM webhooks WHERE connector_id = ? AND is_active = 1"
    if tenant_id:
        sql += " AND tenant_id = ?"
        query_params.append(tenant_id)
    sql += " LIMIT 1"
    row = db.fetch_one(sql, query_params)

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active webhook found for connector '{connector_id}'",
        )

    # Verify HMAC signature if secret is configured
    secret_enc = row.get("secret_enc")
    if secret_enc and x_hub_signature_256:
        try:
            secret = decrypt_secret(secret_enc)
            if not verify_hmac(secret, body_bytes, x_hub_signature_256):
                db.execute(
                    "UPDATE webhooks SET failure_count = failure_count + 1 WHERE id = ?",
                    (row["id"],),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature",
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Signature verification error: {exc}",
            )
    elif secret_enc and not x_hub_signature_256:
        # Signature required but missing
        db.execute(
            "UPDATE webhooks SET failure_count = failure_count + 1 WHERE id = ?",
            (row["id"],),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header",
        )

    # Parse body
    try:
        payload = json.loads(body_bytes)
    except Exception:
        payload = {"raw": body_bytes.decode(errors="replace")}

    # Publish to event bus
    from ..shared.event_bus import get_event_bus
    event_type = x_webhook_event or "webhook.received"
    actual_tenant_id = tenant_id or row["tenant_id"]

    try:
        import asyncio
        bus = get_event_bus()
        event_id = await bus.publish(event_type, connector_id, actual_tenant_id, payload)
    except Exception:
        event_id = None

    # Update stats
    db.execute(
        "UPDATE webhooks SET success_count = success_count + 1, last_triggered = ? WHERE id = ?",
        (utc_now_str(), row["id"]),
    )

    return {
        "received": True,
        "connector_id": connector_id,
        "event_type": event_type,
        "event_id": event_id,
    }
