"""
Audit Log
=========
Universal, tamper-evident audit trail of all significant platform events.
Subscribes to the event bus wildcard ("*") and persists every event as an
audit entry.  Internal callers can also write entries directly via
write_audit_entry() — useful for admin actions that don't go through the bus.

Retention: 90 days, max 10 000 entries (oldest trimmed beyond the cap).

Table: audit_entries
  id            TEXT PK   — UUID (from event or generated)
  ts            TEXT      — ISO-8601 UTC
  event_type    TEXT      — e.g. "alert.threshold.breach"
  actor         TEXT      — originating system component / user
  resource_type TEXT      — derived prefix: "alert", "threat", "workflow", …
  resource_id   TEXT      — optional resource identifier from payload
  action        TEXT      — e.g. "breach", "detected", "completed"
  outcome       TEXT      — "ok" | "error" | "info"
  severity      TEXT      — "critical" | "high" | "medium" | "low" | "info"
  summary       TEXT      — human-readable one-liner

Endpoints:
  GET  /audit-log           — paginated entries, filterable
  GET  /audit-log/stats     — counts by event_type and severity
  GET  /audit-log/export    — CSV download
  POST /audit-log/purge     — delete entries older than N days
"""
from __future__ import annotations

import csv
import io
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit-log", tags=["audit-log"])

_DB_PATH = str(Path(DATA_DIR) / "audit_log.db")
_MAX_ENTRIES = 10_000
_RETENTION_DAYS = 90
_subscribed = False


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS audit_entries (
            id            TEXT PRIMARY KEY,
            ts            TEXT NOT NULL,
            event_type    TEXT NOT NULL,
            actor         TEXT NOT NULL DEFAULT 'system',
            resource_type TEXT NOT NULL DEFAULT '',
            resource_id   TEXT NOT NULL DEFAULT '',
            action        TEXT NOT NULL DEFAULT '',
            outcome       TEXT NOT NULL DEFAULT 'info',
            severity      TEXT NOT NULL DEFAULT 'info',
            summary       TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_ae_ts
            ON audit_entries (ts DESC);
        CREATE INDEX IF NOT EXISTS idx_ae_event
            ON audit_entries (event_type, ts DESC);
        CREATE INDEX IF NOT EXISTS idx_ae_severity
            ON audit_entries (severity, ts DESC);
    """)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)).isoformat()
    con.execute("DELETE FROM audit_entries WHERE ts < ?", (cutoff,))
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Entry construction ────────────────────────────────────────────────────────

def _resource_type(event_type: str) -> str:
    prefix = event_type.split(".")[0]
    return {
        "alert":    "alert_rule",
        "threat":   "threat",
        "email":    "email",
        "agent":    "agent",
        "workflow": "workflow",
        "webhook":  "webhook",
        "metric":   "metric",
        "system":   "system",
    }.get(prefix, prefix)


def _make_summary(event_type: str, payload: dict) -> str:
    if event_type == "alert.threshold.breach":
        return payload.get("message") or (
            f"Alert breach: {payload.get('metric','?')} "
            f"{payload.get('operator','?')} {payload.get('threshold','?')} "
            f"(current={payload.get('value','?')})"
        )
    if event_type == "threat.detected":
        brand  = payload.get("impersonated_brand", "")
        domain = payload.get("domain", "")
        return f"Threat detected: {brand} ({domain})" if brand else f"Threat detected: {domain or '?'}"
    if event_type == "threat.resolved":
        return f"Threat resolved: {payload.get('domain', payload.get('id', '?'))}"
    if event_type == "agent.anomaly":
        return f"Agent anomaly: {payload.get('description', '?')}"
    if event_type.endswith(".failed"):
        return f"{event_type}: {payload.get('error', payload.get('message', 'failure'))}"
    if event_type.endswith(".completed"):
        return f"{event_type.replace('.completed','').replace('.',' ').title()} completed"
    return event_type.replace(".", " ").title()


def _derive_outcome(event_type: str) -> str:
    if event_type.endswith(".failed") or event_type.endswith(".error"):
        return "error"
    return "ok"


def _event_to_entry(event: dict) -> dict:
    payload    = event.get("payload") or {}
    event_type = event.get("type", "unknown")
    parts      = event_type.rsplit(".", 1)
    action     = parts[-1] if len(parts) > 1 else event_type
    return {
        "id":            event.get("id") or str(uuid.uuid4()),
        "ts":            event.get("created_at") or _now(),
        "event_type":    event_type,
        "actor":         event.get("source") or "system",
        "resource_type": _resource_type(event_type),
        "resource_id":   str(payload.get("rule_id") or payload.get("id") or ""),
        "action":        action,
        "outcome":       _derive_outcome(event_type),
        "severity":      event.get("severity") or "info",
        "summary":       _make_summary(event_type, payload),
    }


# ── Write helpers ─────────────────────────────────────────────────────────────

def _insert_entry(entry: dict) -> None:
    try:
        con = _conn()
        con.execute(
            """INSERT OR IGNORE INTO audit_entries
               (id, ts, event_type, actor, resource_type, resource_id,
                action, outcome, severity, summary)
               VALUES (:id,:ts,:event_type,:actor,:resource_type,:resource_id,
                       :action,:outcome,:severity,:summary)""",
            entry,
        )
        # Trim to max cap
        con.execute(
            """DELETE FROM audit_entries WHERE id NOT IN (
                   SELECT id FROM audit_entries ORDER BY ts DESC LIMIT ?)""",
            (_MAX_ENTRIES,),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.debug("AuditLog: write failed: %s", exc)


def write_audit_entry(
    *,
    event_type: str,
    actor: str = "system",
    action: str = "",
    outcome: str = "info",
    severity: str = "info",
    summary: str = "",
    resource_type: str = "",
    resource_id: str = "",
) -> None:
    """Public API for internal callers (admin actions, direct writes)."""
    entry = {
        "id":            str(uuid.uuid4()),
        "ts":            _now(),
        "event_type":    event_type,
        "actor":         actor,
        "resource_type": resource_type or _resource_type(event_type),
        "resource_id":   resource_id,
        "action":        action or event_type.rsplit(".", 1)[-1],
        "outcome":       outcome,
        "severity":      severity,
        "summary":       summary or event_type.replace(".", " ").title(),
    }
    _insert_entry(entry)


# ── Event bus subscriber ──────────────────────────────────────────────────────

async def _on_event(event: dict) -> None:
    entry = _event_to_entry(event)
    _insert_entry(entry)


def ensure_audit_log_running() -> None:
    global _subscribed
    if _subscribed:
        return
    _init_db()
    try:
        from backend.api.event_bus import get_event_bus
        get_event_bus().subscribe("*", _on_event)
        _subscribed = True
        logger.info("AuditLog: subscribed to event bus wildcard")
    except Exception as exc:
        logger.warning("AuditLog: event bus subscription failed: %s", exc)


# ── Query helpers ─────────────────────────────────────────────────────────────

def _build_where(
    event_type: Optional[str],
    severity: Optional[str],
    actor: Optional[str],
    since: Optional[str],
    until: Optional[str],
    q: Optional[str],
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list[Any]  = []
    if event_type:
        clauses.append("event_type = ?"); params.append(event_type)
    if severity:
        clauses.append("severity = ?"); params.append(severity)
    if actor:
        clauses.append("actor = ?"); params.append(actor)
    if since:
        clauses.append("ts >= ?"); params.append(since)
    if until:
        clauses.append("ts <= ?"); params.append(until)
    if q:
        clauses.append("summary LIKE ?"); params.append(f"%{q}%")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="Paginated audit log entries")
async def list_entries(
    limit:      int            = Query(50,  ge=1, le=500),
    offset:     int            = Query(0,   ge=0),
    event_type: Optional[str]  = Query(None),
    severity:   Optional[str]  = Query(None),
    actor:      Optional[str]  = Query(None),
    since:      Optional[str]  = Query(None, description="ISO-8601 lower bound"),
    until:      Optional[str]  = Query(None, description="ISO-8601 upper bound"),
    q:          Optional[str]  = Query(None, description="Full-text search in summary"),
    _auth=Depends(require_local_auth),
):
    where, params = _build_where(event_type, severity, actor, since, until, q)
    try:
        con = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM audit_entries {where}", params
        ).fetchone()[0]
        rows = con.execute(
            f"""SELECT id, ts, event_type, actor, resource_type, resource_id,
                       action, outcome, severity, summary
                FROM audit_entries {where}
                ORDER BY ts DESC LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.error("AuditLog: list query failed: %s", exc)
        return {"entries": [], "total": 0, "limit": limit, "offset": offset}

    keys = ["id", "ts", "event_type", "actor", "resource_type",
            "resource_id", "action", "outcome", "severity", "summary"]
    entries = [dict(zip(keys, r)) for r in rows]
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}


@router.get("/stats", summary="Audit log counts by event type and severity")
async def audit_stats(_auth=Depends(require_local_auth)):
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        con = _conn()
        total = con.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]
        last_24h = con.execute(
            "SELECT COUNT(*) FROM audit_entries WHERE ts >= ?", (cutoff_24h,)
        ).fetchone()[0]
        by_severity = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT severity, COUNT(*) FROM audit_entries GROUP BY severity"
            ).fetchall()
        }
        top_types = [
            {"event_type": r[0], "count": r[1]}
            for r in con.execute(
                """SELECT event_type, COUNT(*) as c FROM audit_entries
                   GROUP BY event_type ORDER BY c DESC LIMIT 10"""
            ).fetchall()
        ]
        con.close()
    except Exception as exc:
        logger.error("AuditLog: stats query failed: %s", exc)
        return {"total": 0, "last_24h": 0, "by_severity": {}, "top_event_types": []}
    return {
        "total":           total,
        "last_24h":        last_24h,
        "by_severity":     by_severity,
        "top_event_types": top_types,
    }


@router.get("/export", summary="Download audit log as CSV")
async def audit_export(
    event_type: Optional[str] = Query(None),
    severity:   Optional[str] = Query(None),
    since:      Optional[str] = Query(None),
    until:      Optional[str] = Query(None),
    _auth=Depends(require_local_auth),
):
    where, params = _build_where(event_type, severity, None, since, until, None)
    try:
        con = _conn()
        rows = con.execute(
            f"""SELECT id, ts, event_type, actor, resource_type, resource_id,
                       action, outcome, severity, summary
                FROM audit_entries {where}
                ORDER BY ts DESC LIMIT 5000""",
            params,
        ).fetchall()
        con.close()
    except Exception:
        rows = []

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "ts", "event_type", "actor", "resource_type",
                     "resource_id", "action", "outcome", "severity", "summary"])
    writer.writerows(rows)
    buf.seek(0)

    filename = f"audit_log_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/purge", summary="Delete entries older than N days")
async def audit_purge(
    days: int = Query(90, ge=1, le=365),
    _auth=Depends(require_local_auth),
):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        con = _conn()
        deleted = con.execute(
            "DELETE FROM audit_entries WHERE ts < ?", (cutoff,)
        ).rowcount
        con.commit()
        con.close()
    except Exception as exc:
        logger.error("AuditLog: purge failed: %s", exc)
        return {"ok": False, "deleted": 0, "message": str(exc)}
    return {"ok": True, "deleted": deleted, "cutoff": cutoff}
