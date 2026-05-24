"""
Change Management
=================
Structured change requests with approval workflow, risk classification,
state machine lifecycle, and optional links to incidents and runbooks.

Tables:
  change_requests  — the change record (title, type, risk, status, owner, dates, rollback plan)
  change_approvals — per-approver approval records (pending / approved / rejected)

State machine:
  draft → review | cancelled
  review → approved | rejected | draft
  approved → in_progress | cancelled
  in_progress → completed | failed | cancelled
  rejected / completed / cancelled / failed → terminal

Endpoints:
  GET    /changes
  POST   /changes                         (201)
  GET    /changes/stats
  GET    /changes/{change_id}
  PATCH  /changes/{change_id}
  DELETE /changes/{change_id}
  POST   /changes/{change_id}/transition
  GET    /changes/{change_id}/approvals
  POST   /changes/{change_id}/approvals   (201)
  PATCH  /changes/{change_id}/approvals/{approval_id}
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/changes", tags=["change_management"])

_DB_PATH = str(Path(DATA_DIR) / "change_management.db")

_CR_COLS = [
    "id", "title", "description", "change_type", "risk_level", "status",
    "owner", "assignee", "planned_start", "planned_end",
    "actual_start", "actual_end", "rollback_plan",
    "linked_incident_id", "linked_runbook_id",
    "approved_by", "approved_at", "change_note",
    "created_at", "updated_at",
]
_APR_COLS = [
    "id", "change_id", "approver", "status", "note", "decided_at", "created_at",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":       {"review", "cancelled"},
    "review":      {"approved", "rejected", "draft"},
    "approved":    {"in_progress", "cancelled"},
    "in_progress": {"completed", "failed", "cancelled"},
    "rejected":    set(),
    "completed":   set(),
    "cancelled":   set(),
    "failed":      set(),
}
_VALID_TYPES       = {"normal", "standard", "emergency"}
_VALID_RISKS       = {"low", "medium", "high", "critical"}
_VALID_STATUSES    = set(_VALID_TRANSITIONS.keys())
_VALID_APR_STATUS  = {"pending", "approved", "rejected"}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS change_requests (
            id                  TEXT PRIMARY KEY,
            title               TEXT NOT NULL,
            description         TEXT NOT NULL DEFAULT '',
            change_type         TEXT NOT NULL DEFAULT 'normal',
            risk_level          TEXT NOT NULL DEFAULT 'low',
            status              TEXT NOT NULL DEFAULT 'draft',
            owner               TEXT NOT NULL DEFAULT '',
            assignee            TEXT NOT NULL DEFAULT '',
            planned_start       TEXT,
            planned_end         TEXT,
            actual_start        TEXT,
            actual_end          TEXT,
            rollback_plan       TEXT NOT NULL DEFAULT '',
            linked_incident_id  TEXT,
            linked_runbook_id   TEXT,
            approved_by         TEXT NOT NULL DEFAULT '',
            approved_at         TEXT,
            change_note         TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS change_approvals (
            id          TEXT PRIMARY KEY,
            change_id   TEXT NOT NULL,
            approver    TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            note        TEXT NOT NULL DEFAULT '',
            decided_at  TEXT,
            created_at  TEXT NOT NULL,
            UNIQUE (change_id, approver)
        );

        CREATE INDEX IF NOT EXISTS idx_cr_status
            ON change_requests (status);
        CREATE INDEX IF NOT EXISTS idx_cr_type
            ON change_requests (change_type);
        CREATE INDEX IF NOT EXISTS idx_cr_risk
            ON change_requests (risk_level);
        CREATE INDEX IF NOT EXISTS idx_cr_owner
            ON change_requests (owner);
        CREATE INDEX IF NOT EXISTS idx_cr_assignee
            ON change_requests (assignee);
        CREATE INDEX IF NOT EXISTS idx_apr_change
            ON change_approvals (change_id);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ChangeCreate(BaseModel):
    title:              str
    description:        str           = ""
    change_type:        str           = "normal"
    risk_level:         str           = "low"
    owner:              str           = ""
    assignee:           str           = ""
    planned_start:      Optional[str] = None
    planned_end:        Optional[str] = None
    rollback_plan:      str           = ""
    linked_incident_id: Optional[str] = None
    linked_runbook_id:  Optional[str] = None
    change_note:        str           = ""


class ChangePatch(BaseModel):
    title:              Optional[str] = None
    description:        Optional[str] = None
    change_type:        Optional[str] = None
    risk_level:         Optional[str] = None
    owner:              Optional[str] = None
    assignee:           Optional[str] = None
    planned_start:      Optional[str] = None
    planned_end:        Optional[str] = None
    actual_start:       Optional[str] = None
    actual_end:         Optional[str] = None
    rollback_plan:      Optional[str] = None
    linked_incident_id: Optional[str] = None
    linked_runbook_id:  Optional[str] = None
    change_note:        Optional[str] = None


class TransitionBody(BaseModel):
    status:     str
    note:       str = ""
    approved_by: str = ""


class ApprovalCreate(BaseModel):
    approver: str
    note:     str = ""


class ApprovalPatch(BaseModel):
    status: str
    note:   str = ""


# ── Sub-routes before /{change_id} ────────────────────────────────────────────

@router.get("", summary="List change requests")
async def list_changes(
    q:           Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    change_type: Optional[str] = Query(None),
    risk_level:  Optional[str] = Query(None),
    limit:       int = Query(50, ge=1, le=500),
    offset:      int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(title LIKE ? OR description LIKE ? OR owner LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if change_type:
        where.append("change_type = ?"); params.append(change_type)
    if risk_level:
        where.append("risk_level = ?"); params.append(risk_level)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(f"SELECT COUNT(*) FROM change_requests {clause}", params).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_CR_COLS)} FROM change_requests {clause} "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {
        "changes": [dict(zip(_CR_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("", status_code=201, summary="Create change request")
async def create_change(body: ChangeCreate, _auth=Depends(require_local_auth)):
    if body.change_type not in _VALID_TYPES:
        raise HTTPException(400, f"change_type must be one of {sorted(_VALID_TYPES)}")
    if body.risk_level not in _VALID_RISKS:
        raise HTTPException(400, f"risk_level must be one of {sorted(_VALID_RISKS)}")
    cr_id = str(uuid.uuid4())
    now   = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO change_requests ({','.join(_CR_COLS)}) "
            f"VALUES ({','.join(['?']*len(_CR_COLS))})",
            (cr_id, body.title, body.description, body.change_type, body.risk_level,
             "draft", body.owner, body.assignee, body.planned_start, body.planned_end,
             None, None, body.rollback_plan,
             body.linked_incident_id, body.linked_runbook_id,
             "", None, body.change_note, now, now),
        )
        con.commit()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"id": cr_id, "title": body.title, "status": "draft"}


@router.get("/stats", summary="Change request statistics")
async def change_stats(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        total = con.execute("SELECT COUNT(*) FROM change_requests").fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM change_requests GROUP BY status"
        ).fetchall()
        by_risk = con.execute(
            "SELECT risk_level, COUNT(*) FROM change_requests GROUP BY risk_level"
        ).fetchall()
        by_type = con.execute(
            "SELECT change_type, COUNT(*) FROM change_requests GROUP BY change_type"
        ).fetchall()
        pending_approvals = con.execute(
            "SELECT COUNT(*) FROM change_approvals WHERE status='pending'"
        ).fetchone()[0]
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {
        "total":            total,
        "by_status":        [{"status": r[0], "count": r[1]} for r in by_status],
        "by_risk":          [{"risk_level": r[0], "count": r[1]} for r in by_risk],
        "by_type":          [{"change_type": r[0], "count": r[1]} for r in by_type],
        "pending_approvals": pending_approvals,
    }


# ── Change-specific routes ────────────────────────────────────────────────────

def _get_change_or_404(con: sqlite3.Connection, change_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_CR_COLS)} FROM change_requests WHERE id=?", (change_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Change request not found")
    return row


@router.get("/{change_id}", summary="Change request detail")
async def get_change(change_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_change_or_404(con, change_id)
        aprs = con.execute(
            f"SELECT {','.join(_APR_COLS)} FROM change_approvals WHERE change_id=? ORDER BY created_at LIMIT 100",
            (change_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    cr = dict(zip(_CR_COLS, row))
    cr["approvals"] = [dict(zip(_APR_COLS, a)) for a in aprs]
    return cr


@router.patch("/{change_id}", summary="Update change request fields")
async def patch_change(change_id: str, body: ChangePatch, _auth=Depends(require_local_auth)):
    updates, params = [], []
    for field in ["title", "description", "owner", "assignee",
                  "planned_start", "planned_end", "actual_start", "actual_end",
                  "rollback_plan", "linked_incident_id", "linked_runbook_id", "change_note"]:
        val = getattr(body, field)
        if val is not None:
            updates.append(f"{field} = ?"); params.append(val)
    if body.change_type is not None:
        if body.change_type not in _VALID_TYPES:
            raise HTTPException(400, f"change_type must be one of {sorted(_VALID_TYPES)}")
        updates.append("change_type = ?"); params.append(body.change_type)
    if body.risk_level is not None:
        if body.risk_level not in _VALID_RISKS:
            raise HTTPException(400, f"risk_level must be one of {sorted(_VALID_RISKS)}")
        updates.append("risk_level = ?"); params.append(body.risk_level)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at = ?"); params.append(_now())
    params.append(change_id)
    try:
        con = _conn()
        con.execute(f"UPDATE change_requests SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close(); raise HTTPException(404, "Change request not found")
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"ok": True}


@router.delete("/{change_id}", status_code=204, summary="Delete change request")
async def delete_change(change_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute("SELECT status FROM change_requests WHERE id=?", (change_id,)).fetchone()
        if not row:
            con.close(); raise HTTPException(404, "Change request not found")
        if row[0] == "in_progress":
            con.close(); raise HTTPException(409, "Cannot delete an in-progress change")
        con.execute("DELETE FROM change_approvals WHERE change_id=?", (change_id,))
        con.execute("DELETE FROM change_requests WHERE id=?", (change_id,))
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")


@router.post("/{change_id}/transition", summary="Transition status")
async def transition_change(
    change_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(400, f"Unknown status '{body.status}'")
    try:
        con = _conn()
        row = _get_change_or_404(con, change_id)
        cr  = dict(zip(_CR_COLS, row))
        allowed = _VALID_TRANSITIONS.get(cr["status"], set())
        if body.status not in allowed:
            con.close()
            raise HTTPException(400,
                f"Cannot transition from '{cr['status']}' to '{body.status}'. "
                f"Allowed: {sorted(allowed) or 'none (terminal)'}")
        now = _now()
        extra_sets, extra_params = [], []
        if body.status == "in_progress" and not cr["actual_start"]:
            extra_sets.append("actual_start = ?"); extra_params.append(now)
        if body.status in ("completed", "failed", "cancelled") and not cr["actual_end"]:
            extra_sets.append("actual_end = ?"); extra_params.append(now)
        if body.approved_by and body.status == "approved":
            extra_sets += ["approved_by = ?", "approved_at = ?"]
            extra_params += [body.approved_by, now]
        sets = ["status = ?", "change_note = ?", "updated_at = ?"] + extra_sets
        vals = [body.status, body.note or cr["change_note"], now] + extra_params + [change_id]
        con.execute(f"UPDATE change_requests SET {', '.join(sets)} WHERE id=?", vals)
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"ok": True, "status": body.status}


# ── Approvals ─────────────────────────────────────────────────────────────────

@router.get("/{change_id}/approvals", summary="List approvals")
async def list_approvals(change_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_change_or_404(con, change_id)
        rows = con.execute(
            f"SELECT {','.join(_APR_COLS)} FROM change_approvals WHERE change_id=? ORDER BY created_at LIMIT 100",
            (change_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"approvals": [dict(zip(_APR_COLS, r)) for r in rows]}


@router.post("/{change_id}/approvals", status_code=201, summary="Add approver")
async def add_approval(change_id: str, body: ApprovalCreate, _auth=Depends(require_local_auth)):
    if not body.approver.strip():
        raise HTTPException(400, "approver is required")
    apr_id = str(uuid.uuid4())
    now = _now()
    try:
        con = _conn()
        _get_change_or_404(con, change_id)
        con.execute(
            f"INSERT INTO change_approvals ({','.join(_APR_COLS)}) VALUES ({','.join(['?']*len(_APR_COLS))})",
            (apr_id, change_id, body.approver, "pending", body.note, None, now),
        )
        con.commit(); con.close()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Approver '{body.approver}' already added to this change")
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"id": apr_id, "approver": body.approver, "status": "pending"}


@router.patch("/{change_id}/approvals/{approval_id}", summary="Update approval decision")
async def update_approval(
    change_id: str, approval_id: str, body: ApprovalPatch, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_APR_STATUS:
        raise HTTPException(400, f"status must be one of {sorted(_VALID_APR_STATUS)}")
    now = _now()
    decided_at = now if body.status != "pending" else None
    try:
        con = _conn()
        con.execute(
            "UPDATE change_approvals SET status=?, note=?, decided_at=? "
            "WHERE id=? AND change_id=?",
            (body.status, body.note, decided_at, approval_id, change_id),
        )
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close(); raise HTTPException(404, "Approval not found")
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"ok": True, "status": body.status}
