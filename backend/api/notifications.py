"""
Notification Center
===================
Persistent in-app notification feed that aggregates critical platform events
so operators get an at-a-glance view without configuring webhooks first.

Subscribes to the event bus for high-signal event types and persists each
one as a notification record.  The UI polls this API and shows a badge count.

Event types captured:
  alert.threshold.breach  → Alert rule fired
  threat.detected         → Lookalike / threat detected
  agent.anomaly           → Autonomous agent anomaly
  workflow.failed         → Workflow execution failed
  system.degraded         → Platform component degraded
  system.sla_breach       → SLA threshold breached

Endpoints:
  GET  /notifications              — list (newest first, optional unread_only)
  GET  /notifications/count        — unread count (cheap poll target)
  POST /notifications/{id}/read    — mark one as read
  POST /notifications/read-all     — mark all as read
  DELETE /notifications/{id}       — delete one
  DELETE /notifications            — clear all
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])

_DB_PATH   = str(Path(DATA_DIR) / "notifications.db")
_MAX_STORE = 500   # oldest trimmed once this is exceeded

# Event types to capture → (title template, navigate-to view)
_CAPTURED: Dict[str, Dict[str, str]] = {
    "alert.threshold.breach": {"title": "Alert Rule Breached",  "view": "command"},
    "threat.detected":        {"title": "Threat Detected",      "view": "command"},
    "agent.anomaly":          {"title": "Agent Anomaly",         "view": "command"},
    "workflow.failed":        {"title": "Workflow Failed",       "view": "workflows"},
    "system.degraded":        {"title": "System Degraded",      "view": "command"},
    "system.sla_breach":      {"title": "SLA Breach",           "view": "command"},
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS notifications (
            id          TEXT PRIMARY KEY,
            event_type  TEXT NOT NULL,
            title       TEXT NOT NULL,
            body        TEXT,
            severity    TEXT DEFAULT 'low',
            source      TEXT,
            view_hint   TEXT,
            is_read     INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notif_read    ON notifications (is_read, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notif_created ON notifications (created_at DESC);
    """)
    con.close()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trim(con: sqlite3.Connection) -> None:
    max_store = min(_MAX_STORE, get_runtime_control().service_limits("notifications")["queue_limit"])
    con.execute(
        """DELETE FROM notifications WHERE id NOT IN (
               SELECT id FROM notifications ORDER BY created_at DESC LIMIT ?)""",
        (max_store,),
    )


# ── Event bus subscriber ──────────────────────────────────────────────────────

async def _on_event(event: Dict[str, Any]) -> None:
    event_type = event.get("type", "")
    meta = _CAPTURED.get(event_type)
    if meta is None:
        return

    payload   = event.get("payload", {})
    severity  = event.get("severity", "low")
    source    = event.get("source", "")

    # Build a human-readable body from the payload
    body = _build_body(event_type, payload)

    notif_id = str(uuid.uuid4())
    try:
        con = _conn()
        con.execute(
            """INSERT INTO notifications
               (id, event_type, title, body, severity, source, view_hint, is_read, created_at)
               VALUES (?,?,?,?,?,?,?,0,?)""",
            (notif_id, event_type, meta["title"], body, severity, source, meta.get("view"), _now()),
        )
        _trim(con)
        con.commit()
        con.close()
    except Exception as exc:
        logger.debug("Notification store failed: %s", exc)


def _build_body(event_type: str, payload: Dict) -> str:
    if event_type == "alert.threshold.breach":
        return payload.get("message") or (
            f"{payload.get('metric')} {payload.get('operator')} {payload.get('threshold')} "
            f"(current={payload.get('value')})"
        )
    if event_type == "threat.detected":
        brand = payload.get("impersonated_brand") or payload.get("brand") or ""
        domain = payload.get("domain") or payload.get("lookalike_domain") or ""
        return f"{brand} lookalike: {domain}" if (brand or domain) else "Lookalike domain detected"
    if event_type == "agent.anomaly":
        return payload.get("description") or payload.get("message") or "Anomaly detected by autonomous agent"
    if event_type == "workflow.failed":
        return payload.get("error") or payload.get("workflow_name") or "Workflow execution failed"
    if event_type in ("system.degraded", "system.sla_breach"):
        return payload.get("message") or payload.get("component") or event_type.replace(".", " ").title()
    return json.dumps(payload)[:120] if payload else ""


# ── Startup (idempotent) ──────────────────────────────────────────────────────

_subscribed = False


def ensure_notification_center() -> None:
    global _subscribed
    if _subscribed:
        return
    if not get_runtime_control().is_service_enabled("notifications"):
        logger.info("Notification center disabled by runtime policy")
        return
    try:
        _init_db()
        from backend.api.event_bus import get_event_bus
        bus = get_event_bus()
        for event_type in _CAPTURED:
            bus.subscribe(event_type, _on_event)
        _subscribed = True
        logger.info("Notification center subscribed to %d event types", len(_CAPTURED))
    except Exception as exc:
        logger.warning("Notification center subscription failed: %s", exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List notifications (newest first)")
async def list_notifications(
    limit:       int  = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        con.row_factory = sqlite3.Row
        where = "WHERE is_read=0" if unread_only else ""
        rows  = con.execute(
            f"SELECT * FROM notifications {where} ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        total_unread = con.execute("SELECT COUNT(*) FROM notifications WHERE is_read=0").fetchone()[0]
        con.close()
        notifs = [dict(r) for r in rows]
        for n in notifs:
            n["is_read"] = bool(n["is_read"])
        return {"notifications": notifs, "unread": total_unread, "count": len(notifs)}
    except Exception as exc:
        return {"notifications": [], "unread": 0, "count": 0, "error": str(exc)}


@router.get("/count", summary="Unread notification count (cheap poll)")
async def unread_count(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        n = con.execute("SELECT COUNT(*) FROM notifications WHERE is_read=0").fetchone()[0]
        con.close()
        return {"unread": n}
    except Exception:
        return {"unread": 0}


@router.get("/status", summary="Notification queue status")
async def notification_status(_auth=Depends(require_local_auth)):
    limits = get_runtime_control().service_limits("notifications")
    capacity = min(_MAX_STORE, limits["queue_limit"])
    try:
        con = _conn()
        total = con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        unread = con.execute("SELECT COUNT(*) FROM notifications WHERE is_read=0").fetchone()[0]
        con.close()
    except Exception as exc:
        return {
            "service": "notifications",
            "healthy": False,
            "total": 0,
            "unread": 0,
            "capacity": capacity,
            "pressure": 0.0,
            "error": str(exc),
        }
    pressure = round(total / capacity, 4) if capacity else 0.0
    return {
        "service": "notifications",
        "healthy": pressure < 0.9,
        "total": total,
        "unread": unread,
        "capacity": capacity,
        "pressure": pressure,
    }


@router.post("/{notif_id}/read", summary="Mark a notification as read")
async def mark_read(notif_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("UPDATE notifications SET is_read=1 WHERE id=?", (notif_id,))
        con.commit()
        con.close()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/read-all", summary="Mark all notifications as read")
async def mark_all_read(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        n = con.execute("UPDATE notifications SET is_read=1 WHERE is_read=0").rowcount
        con.commit()
        con.close()
        return {"ok": True, "marked": n}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.delete("/{notif_id}", summary="Delete a notification", status_code=204)
async def delete_notification(notif_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM notifications WHERE id=?", (notif_id,))
        con.commit()
        con.close()
    except Exception:
        pass


@router.delete("", summary="Clear all notifications", status_code=204)
async def clear_all(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM notifications")
        con.commit()
        con.close()
    except Exception:
        pass
