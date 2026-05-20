"""
Outbound Webhooks
=================
Push platform events to external URLs — Slack, PagerDuty, n8n, custom endpoints.

Each webhook registration specifies:
  - A target URL (SSRF-validated)
  - Event type patterns to match ("*", "threat.*", "email.received", etc.)
  - An HMAC-SHA256 signing secret
  - A minimum severity filter
  - Optional extra HTTP headers

The dispatcher subscribes to the event bus "*" channel so it receives every
event, then fans out to all matching webhooks with retry logic (3 attempts,
exponential back-off: 5s → 30s → 120s).

Delivery log is persisted to SQLite so operators can audit what was sent and
whether it succeeded.

Endpoints:
  GET    /webhooks                   — list webhooks
  POST   /webhooks                   — create webhook
  POST   /webhooks/test              — send a test ping
  GET    /webhooks/{id}              — get webhook
  PATCH  /webhooks/{id}             — update webhook
  DELETE /webhooks/{id}             — delete webhook
  GET    /webhooks/{id}/deliveries  — delivery log
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control
from backend.security.ssrf import validate_outbound_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_DB_PATH = str(Path(DATA_DIR) / "webhooks.db")

_SEVERITIES   = ("low", "medium", "high", "critical")
_MAX_RETRIES  = 3
_TIMEOUT_S    = 10.0
_RETRY_DELAYS = (5, 30, 120)


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS webhooks (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            url          TEXT NOT NULL,
            events       TEXT NOT NULL DEFAULT '["*"]',
            secret       TEXT DEFAULT '',
            headers      TEXT DEFAULT '{}',
            min_severity TEXT DEFAULT 'low',
            is_active    INTEGER DEFAULT 1,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id          TEXT PRIMARY KEY,
            webhook_id  TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            event_id    TEXT,
            url         TEXT NOT NULL,
            status_code INTEGER,
            success     INTEGER DEFAULT 0,
            attempt     INTEGER DEFAULT 1,
            duration_ms INTEGER,
            error       TEXT,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wh_deliveries
            ON webhook_deliveries (webhook_id, created_at DESC);
    """)
    con.close()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Pattern matching ──────────────────────────────────────────────────────────

def _event_matches(pattern: str, event_type: str) -> bool:
    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type


def _webhook_matches(webhook: Dict, event_type: str, severity: str) -> bool:
    try:
        patterns = json.loads(webhook.get("events") or '["*"]')
    except Exception:
        patterns = ["*"]
    if not any(_event_matches(p, event_type) for p in patterns):
        return False
    sev_rank = _SEVERITIES.index(severity) if severity in _SEVERITIES else 0
    min_sev  = webhook.get("min_severity", "low")
    min_rank = _SEVERITIES.index(min_sev) if min_sev in _SEVERITIES else 0
    return sev_rank >= min_rank


# ── HMAC signing ──────────────────────────────────────────────────────────────

def _sign_payload(secret: str, payload: bytes) -> str:
    if not secret:
        return ""
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ── HTTP delivery ─────────────────────────────────────────────────────────────

async def _post_one(
    webhook_id: str,
    url: str,
    secret: str,
    extra_headers: Dict,
    payload: Dict,
    event_type: str,
    event_id: str,
) -> None:
    body = json.dumps(payload).encode()
    sig  = _sign_payload(secret, body)
    base_headers: Dict[str, str] = {
        "Content-Type":       "application/json",
        "X-INTEMO-Event":     event_type,
        "X-INTEMO-Delivery":  str(uuid.uuid4()),
        "X-INTEMO-Timestamp": str(int(time.time())),
        **{str(k): str(v) for k, v in extra_headers.items()},
    }
    if sig:
        base_headers["X-INTEMO-Signature"] = sig

    for attempt in range(1, _MAX_RETRIES + 1):
        delivery_id = str(uuid.uuid4())
        t0          = time.monotonic()
        status_code: Optional[int] = None
        error_msg:   Optional[str] = None
        success      = False

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
                resp = await client.post(url, content=body, headers=base_headers)
                status_code = resp.status_code
                success = 200 <= resp.status_code < 300
        except Exception as exc:
            error_msg = str(exc)

        duration_ms = int((time.monotonic() - t0) * 1000)

        try:
            con = _conn()
            con.execute(
                """INSERT INTO webhook_deliveries
                   (id, webhook_id, event_type, event_id, url,
                    status_code, success, attempt, duration_ms, error, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (delivery_id, webhook_id, event_type, event_id, url,
                 status_code, int(success), attempt, duration_ms, error_msg, _now()),
            )
            con.commit()
            con.close()
        except Exception as db_exc:
            logger.debug("Webhook delivery log write failed: %s", db_exc)

        if success:
            return

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAYS[attempt - 1])

    logger.warning(
        "Webhook %s: all %d delivery attempts failed for %s",
        webhook_id[:8], _MAX_RETRIES, url,
    )


# ── Event bus dispatcher ──────────────────────────────────────────────────────

async def dispatch_event(event: Dict) -> None:
    """Receive every platform event via bus '*' subscription and fan out."""
    event_type = event.get("type", "")
    severity   = event.get("severity", "low")
    event_id   = event.get("id", "")

    try:
        con = _conn()
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM webhooks WHERE is_active=1").fetchall()
        con.close()
    except Exception as exc:
        logger.debug("Webhook dispatch DB read failed: %s", exc)
        return

    payload = {
        "id":          event_id,
        "type":        event_type,
        "severity":    severity,
        "source":      event.get("source", ""),
        "payload":     event.get("payload", {}),
        "occurred_at": event.get("created_at", _now()),
        "platform":    "INTEMO",
    }

    for row in rows:
        wh = dict(row)
        if not _webhook_matches(wh, event_type, severity):
            continue
        try:
            extra = json.loads(wh.get("headers") or "{}")
        except Exception:
            extra = {}
        asyncio.create_task(_post_one(
            webhook_id=wh["id"],
            url=wh["url"],
            secret=wh.get("secret", ""),
            extra_headers=extra,
            payload=payload,
            event_type=event_type,
            event_id=event_id,
        ))


# ── Startup (idempotent) ──────────────────────────────────────────────────────

_subscribed = False


def ensure_webhook_dispatcher() -> None:
    global _subscribed
    if _subscribed:
        return
    if not get_runtime_control().is_service_enabled("webhooks"):
        logger.info("Webhook dispatcher disabled by runtime policy")
        return
    try:
        _init_db()
        from backend.api.event_bus import get_event_bus
        get_event_bus().subscribe("*", dispatch_event)
        _subscribed = True
        logger.info("Outbound webhook dispatcher subscribed to event bus")
    except Exception as exc:
        logger.warning("Webhook dispatcher subscription failed: %s", exc)


# ── Pydantic models ───────────────────────────────────────────────────────────

class WebhookCreate(BaseModel):
    name:         str
    url:          str
    events:       List[str]           = Field(default_factory=lambda: ["*"])
    secret:       str                 = ""
    headers:      Dict[str, str]      = Field(default_factory=dict)
    min_severity: str                 = "low"


class WebhookUpdate(BaseModel):
    name:         Optional[str]            = None
    url:          Optional[str]            = None
    events:       Optional[List[str]]      = None
    secret:       Optional[str]            = None
    headers:      Optional[Dict[str, str]] = None
    min_severity: Optional[str]            = None
    is_active:    Optional[bool]           = None


class WebhookTest(BaseModel):
    url:        str
    secret:     str             = ""
    headers:    Dict[str, str]  = Field(default_factory=dict)
    event_type: str             = "test.ping"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_dict(row) -> Dict:
    d = dict(row)
    try:
        d["events"] = json.loads(d.get("events") or '["*"]')
    except Exception:
        d["events"] = ["*"]
    try:
        d["headers"] = json.loads(d.get("headers") or "{}")
    except Exception:
        d["headers"] = {}
    d["is_active"] = bool(d.get("is_active", 1))
    return d


def _validate_url(url: str) -> None:
    decision = validate_outbound_url(url)
    if not decision.allowed:
        raise HTTPException(400, f"URL not allowed: {decision.reason}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List all registered webhooks")
async def list_webhooks(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM webhooks ORDER BY created_at DESC").fetchall()
        con.close()
        return {"webhooks": [_row_to_dict(r) for r in rows], "count": len(rows)}
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.post("/test", summary="Send a test ping to a URL")
async def test_webhook(body: WebhookTest, _auth=Depends(require_local_auth)):
    _validate_url(body.url)
    test_payload = {
        "id":          str(uuid.uuid4()),
        "type":        body.event_type,
        "severity":    "low",
        "source":      "webhook_test",
        "payload":     {"message": "INTEMO webhook test ping"},
        "occurred_at": _now(),
        "platform":    "INTEMO",
    }
    raw = json.dumps(test_payload).encode()
    sig = _sign_payload(body.secret, raw)
    headers: Dict[str, str] = {
        "Content-Type":       "application/json",
        "X-INTEMO-Event":     body.event_type,
        "X-INTEMO-Delivery":  str(uuid.uuid4()),
        "X-INTEMO-Timestamp": str(int(time.time())),
        **{str(k): str(v) for k, v in body.headers.items()},
    }
    if sig:
        headers["X-INTEMO-Signature"] = sig

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.post(body.url, content=raw, headers=headers)
        duration_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok":          200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "duration_ms": duration_ms,
            "url":         body.url,
        }
    except Exception as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok":          False,
            "status_code": None,
            "duration_ms": duration_ms,
            "error":       str(exc),
            "url":         body.url,
        }


@router.post("", summary="Register a new webhook", status_code=201)
async def create_webhook(body: WebhookCreate, _auth=Depends(require_local_auth)):
    _validate_url(body.url)
    wh_id = str(uuid.uuid4())
    now   = _now()
    try:
        con = _conn()
        con.execute(
            """INSERT INTO webhooks
               (id, name, url, events, secret, headers, min_severity, is_active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,1,?,?)""",
            (wh_id, body.name, body.url,
             json.dumps(body.events), body.secret,
             json.dumps(body.headers), body.min_severity, now, now),
        )
        con.commit()
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM webhooks WHERE id=?", (wh_id,)).fetchone()
        con.close()
        return _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.get("/{webhook_id}", summary="Get a webhook by ID")
async def get_webhook(webhook_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
        con.close()
        if not row:
            raise HTTPException(404, "Webhook not found")
        return _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.patch("/{webhook_id}", summary="Update a webhook")
async def update_webhook(
    webhook_id: str, body: WebhookUpdate, _auth=Depends(require_local_auth)
):
    if body.url is not None:
        _validate_url(body.url)
    fields: Dict[str, Any] = {}
    if body.name         is not None: fields["name"]         = body.name
    if body.url          is not None: fields["url"]          = body.url
    if body.events       is not None: fields["events"]        = json.dumps(body.events)
    if body.secret       is not None: fields["secret"]        = body.secret
    if body.headers      is not None: fields["headers"]       = json.dumps(body.headers)
    if body.min_severity is not None: fields["min_severity"]  = body.min_severity
    if body.is_active    is not None: fields["is_active"]     = int(body.is_active)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    try:
        con = _conn()
        result = con.execute(
            f"UPDATE webhooks SET {set_clause} WHERE id=?",
            (*fields.values(), webhook_id),
        )
        con.commit()
        if result.rowcount == 0:
            con.close()
            raise HTTPException(404, "Webhook not found")
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM webhooks WHERE id=?", (webhook_id,)).fetchone()
        con.close()
        return _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.delete("/{webhook_id}", summary="Delete a webhook", status_code=204)
async def delete_webhook(webhook_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        result = con.execute("DELETE FROM webhooks WHERE id=?", (webhook_id,))
        con.commit()
        con.close()
        if result.rowcount == 0:
            raise HTTPException(404, "Webhook not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.get("/{webhook_id}/deliveries", summary="Delivery log for a webhook")
async def webhook_deliveries(
    webhook_id: str,
    limit: int = 50,
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT * FROM webhook_deliveries
               WHERE webhook_id=? ORDER BY created_at DESC LIMIT ?""",
            (webhook_id, limit),
        ).fetchall()
        total = con.execute(
            "SELECT COUNT(*) FROM webhook_deliveries WHERE webhook_id=?", (webhook_id,)
        ).fetchone()[0]
        con.close()
        deliveries = [dict(r) for r in rows]
        for d in deliveries:
            d["success"] = bool(d["success"])
        return {"deliveries": deliveries, "total": total, "webhook_id": webhook_id}
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")
