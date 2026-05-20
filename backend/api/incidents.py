"""
Incident Manager
================
Tracks operational incidents from creation through acknowledgement to resolution.
Subscribes to alert.threshold.breach events and auto-creates incidents.
Deduplicates: if an open incident already exists for a given alert rule,
repeated breaches add a timeline entry rather than creating a new record.

Status lifecycle:  open → acknowledged → resolved  (can also reopen)

Tables:
  incidents
    id, title, description, severity, status, source,
    trigger_event_id, rule_id, metric,
    created_at, updated_at, acknowledged_at, resolved_at, assigned_to

  incident_timeline
    id, incident_id, ts, actor, action, note

Endpoints:
  GET    /incidents              — list, filterable
  POST   /incidents              — create manually
  GET    /incidents/stats        — counts by status/severity
  GET    /incidents/{id}         — detail + timeline
  PATCH  /incidents/{id}         — update (status, assigned_to)
  POST   /incidents/{id}/acknowledge
  POST   /incidents/{id}/resolve
  POST   /incidents/{id}/comment
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/incidents", tags=["incidents"])

_DB_PATH = str(Path(DATA_DIR) / "incidents.db")
_subscribed = False

# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS incidents (
            id                TEXT PRIMARY KEY,
            title             TEXT NOT NULL,
            description       TEXT NOT NULL DEFAULT '',
            severity          TEXT NOT NULL DEFAULT 'medium',
            status            TEXT NOT NULL DEFAULT 'open',
            source            TEXT NOT NULL DEFAULT 'system',
            trigger_event_id  TEXT NOT NULL DEFAULT '',
            rule_id           TEXT NOT NULL DEFAULT '',
            metric            TEXT NOT NULL DEFAULT '',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL,
            acknowledged_at   TEXT,
            resolved_at       TEXT,
            assigned_to       TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS incident_timeline (
            id          TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL,
            ts          TEXT NOT NULL,
            actor       TEXT NOT NULL DEFAULT 'system',
            action      TEXT NOT NULL,
            note        TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_inc_status
            ON incidents (status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_inc_rule
            ON incidents (rule_id, status);
        CREATE INDEX IF NOT EXISTS idx_tl_incident
            ON incident_timeline (incident_id, ts ASC);
    """)
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Helpers ───────────────────────────────────────────────────────────────────

_INC_COLS = [
    "id", "title", "description", "severity", "status", "source",
    "trigger_event_id", "rule_id", "metric",
    "created_at", "updated_at", "acknowledged_at", "resolved_at", "assigned_to",
]
_TL_COLS = ["id", "incident_id", "ts", "actor", "action", "note"]


def _row_to_inc(row) -> dict:
    return dict(zip(_INC_COLS, row))


def _row_to_tl(row) -> dict:
    return dict(zip(_TL_COLS, row))


def _add_timeline(incident_id: str, actor: str, action: str, note: str = "") -> None:
    try:
        con = _conn()
        con.execute(
            "INSERT INTO incident_timeline (id,incident_id,ts,actor,action,note) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), incident_id, _now(), actor, action, note),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.debug("IncidentManager: timeline write failed: %s", exc)


def _create_incident(
    *,
    title: str,
    description: str = "",
    severity: str = "medium",
    source: str = "system",
    trigger_event_id: str = "",
    rule_id: str = "",
    metric: str = "",
    assigned_to: str = "",
) -> dict:
    inc_id = str(uuid.uuid4())
    now = _now()
    row_vals = (
        inc_id, title, description, severity, "open", source,
        trigger_event_id, rule_id, metric, now, now, None, None, assigned_to,
    )
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO incidents ({','.join(_INC_COLS)}) VALUES ({','.join(['?']*len(_INC_COLS))})",
            row_vals,
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.error("IncidentManager: create failed: %s", exc)
        raise

    _add_timeline(inc_id, actor=source, action="created",
                  note=f"Incident created: {title}")

    try:
        from backend.api.event_bus import get_event_bus
        import asyncio
        asyncio.create_task(get_event_bus().publish({
            "type":       "incident.created",
            "severity":   severity,
            "source":     "incident_manager",
            "id":         str(uuid.uuid4()),
            "payload":    {"incident_id": inc_id, "title": title, "rule_id": rule_id},
            "created_at": now,
        }))
    except Exception:
        pass

    return {"id": inc_id, "title": title, "severity": severity, "status": "open"}


def _get_open_for_rule(rule_id: str) -> Optional[str]:
    if not rule_id:
        return None
    try:
        con = _conn()
        row = con.execute(
            "SELECT id FROM incidents WHERE rule_id=? AND status IN ('open','acknowledged')",
            (rule_id,),
        ).fetchone()
        con.close()
        return row[0] if row else None
    except Exception:
        return None


# ── Event bus subscriber ──────────────────────────────────────────────────────

async def _on_breach(event: dict) -> None:
    payload   = event.get("payload") or {}
    rule_id   = str(payload.get("rule_id", ""))
    metric    = str(payload.get("metric", "unknown"))
    severity  = event.get("severity") or "medium"
    message   = payload.get("message", f"{metric} threshold breached")

    existing_id = _get_open_for_rule(rule_id)
    if existing_id:
        _add_timeline(
            existing_id, actor="alert_engine",
            action="repeated_breach", note=message,
        )
        return

    _create_incident(
        title=message,
        description=(
            f"Rule '{payload.get('rule_name', rule_id)}' fired. "
            f"{metric} {payload.get('operator','?')} {payload.get('threshold','?')} "
            f"(current={payload.get('value','?')})."
        ),
        severity=severity,
        source="alert_rules",
        trigger_event_id=event.get("id", ""),
        rule_id=rule_id,
        metric=metric,
    )


def ensure_incident_manager_running() -> None:
    global _subscribed
    if _subscribed:
        return
    if not get_runtime_control().is_service_enabled("incidents"):
        logger.info("IncidentManager: disabled by runtime policy")
        return
    _init_db()
    try:
        from backend.api.event_bus import get_event_bus
        get_event_bus().subscribe("alert.threshold.breach", _on_breach)
        _subscribed = True
        logger.info("IncidentManager: subscribed to alert.threshold.breach")
    except Exception as exc:
        logger.warning("IncidentManager: event bus subscription failed: %s", exc)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class IncidentCreate(BaseModel):
    title:       str
    description: str = ""
    severity:    str = "medium"
    assigned_to: str = ""


class IncidentPatch(BaseModel):
    assigned_to: Optional[str] = None
    status:      Optional[str] = None


class CommentBody(BaseModel):
    note: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List incidents")
async def list_incidents(
    status:   Optional[str] = Query(None, description="open|acknowledged|resolved"),
    severity: Optional[str] = Query(None),
    limit:    int            = Query(50, ge=1, le=500),
    offset:   int            = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    clauses, params = [], []
    if status:
        clauses.append("status = ?"); params.append(status)
    if severity:
        clauses.append("severity = ?"); params.append(severity)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    try:
        con = _conn()
        total = con.execute(f"SELECT COUNT(*) FROM incidents {where}", params).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_INC_COLS)} FROM incidents {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.error("IncidentManager: list failed: %s", exc)
        return {"incidents": [], "total": 0, "limit": limit, "offset": offset}
    return {"incidents": [_row_to_inc(r) for r in rows], "total": total,
            "limit": limit, "offset": offset}


@router.post("", status_code=201, summary="Create incident manually")
async def create_incident(body: IncidentCreate, _auth=Depends(require_local_auth)):
    inc = _create_incident(
        title=body.title,
        description=body.description,
        severity=body.severity,
        source="manual",
        assigned_to=body.assigned_to,
    )
    return inc


@router.get("/stats", summary="Incident counts by status and severity")
async def incident_stats(_auth=Depends(require_local_auth)):
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        con = _conn()
        by_status = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT status, COUNT(*) FROM incidents GROUP BY status"
            ).fetchall()
        }
        by_severity = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT severity, COUNT(*) FROM incidents GROUP BY severity"
            ).fetchall()
        }
        opened_24h = con.execute(
            "SELECT COUNT(*) FROM incidents WHERE created_at >= ?", (cutoff_24h,)
        ).fetchone()[0]
        resolved_24h = con.execute(
            "SELECT COUNT(*) FROM incidents WHERE resolved_at >= ?", (cutoff_24h,)
        ).fetchone()[0]
        total = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
        con.close()
    except Exception:
        return {"total": 0, "by_status": {}, "by_severity": {}, "opened_24h": 0, "resolved_24h": 0}
    return {
        "total":        total,
        "by_status":    by_status,
        "by_severity":  by_severity,
        "opened_24h":   opened_24h,
        "resolved_24h": resolved_24h,
    }


@router.get("/{incident_id}", summary="Incident detail with timeline")
async def get_incident(incident_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_INC_COLS)} FROM incidents WHERE id=?", (incident_id,)
        ).fetchone()
        if not row:
            con.close()
            raise HTTPException(404, "Incident not found")
        timeline = con.execute(
            f"SELECT {','.join(_TL_COLS)} FROM incident_timeline WHERE incident_id=? ORDER BY ts ASC",
            (incident_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("IncidentManager: get failed: %s", exc)
        raise HTTPException(500, "DB error")
    return {
        "incident": _row_to_inc(row),
        "timeline": [_row_to_tl(t) for t in timeline],
    }


@router.patch("/{incident_id}", summary="Update incident fields")
async def patch_incident(
    incident_id: str, body: IncidentPatch, _auth=Depends(require_local_auth)
):
    updates, params = [], []
    if body.assigned_to is not None:
        updates.append("assigned_to = ?"); params.append(body.assigned_to)
    if body.status is not None:
        if body.status not in ("open", "acknowledged", "resolved"):
            raise HTTPException(400, "status must be open|acknowledged|resolved")
        updates.append("status = ?"); params.append(body.status)
        if body.status == "acknowledged":
            updates.append("acknowledged_at = ?"); params.append(_now())
        elif body.status == "resolved":
            updates.append("resolved_at = ?"); params.append(_now())
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at = ?"); params.append(_now())
    params.append(incident_id)
    try:
        con = _conn()
        con.execute(
            f"UPDATE incidents SET {', '.join(updates)} WHERE id=?", params
        )
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "Incident not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if body.status:
        _add_timeline(incident_id, actor="operator", action=body.status,
                      note=f"Status changed to {body.status}")
    return {"ok": True}


@router.post("/{incident_id}/acknowledge", summary="Acknowledge an incident")
async def acknowledge_incident(incident_id: str, _auth=Depends(require_local_auth)):
    now = _now()
    try:
        con = _conn()
        con.execute(
            "UPDATE incidents SET status='acknowledged', acknowledged_at=?, updated_at=? WHERE id=? AND status='open'",
            (now, now, incident_id),
        )
        changed = con.execute("SELECT changes()").fetchone()[0]
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if changed == 0:
        raise HTTPException(404, "Incident not found or not in 'open' state")
    _add_timeline(incident_id, actor="operator", action="acknowledged",
                  note="Incident acknowledged")
    return {"ok": True}


@router.post("/{incident_id}/resolve", summary="Resolve an incident")
async def resolve_incident(incident_id: str, _auth=Depends(require_local_auth)):
    now = _now()
    try:
        con = _conn()
        con.execute(
            "UPDATE incidents SET status='resolved', resolved_at=?, updated_at=? WHERE id=? AND status IN ('open','acknowledged')",
            (now, now, incident_id),
        )
        changed = con.execute("SELECT changes()").fetchone()[0]
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if changed == 0:
        raise HTTPException(404, "Incident not found or already resolved")
    _add_timeline(incident_id, actor="operator", action="resolved",
                  note="Incident resolved")
    try:
        from backend.api.event_bus import get_event_bus
        import asyncio
        asyncio.create_task(get_event_bus().publish({
            "type":       "incident.resolved",
            "severity":   "info",
            "source":     "incident_manager",
            "id":         str(uuid.uuid4()),
            "payload":    {"incident_id": incident_id},
            "created_at": now,
        }))
    except Exception:
        pass
    return {"ok": True}


@router.post("/{incident_id}/comment", summary="Add a comment to an incident")
async def add_comment(
    incident_id: str, body: CommentBody, _auth=Depends(require_local_auth)
):
    if not body.note.strip():
        raise HTTPException(400, "Comment note cannot be empty")
    try:
        con = _conn()
        exists = con.execute(
            "SELECT 1 FROM incidents WHERE id=?", (incident_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not exists:
        raise HTTPException(404, "Incident not found")
    _add_timeline(incident_id, actor="operator", action="commented", note=body.note.strip())
    return {"ok": True}
