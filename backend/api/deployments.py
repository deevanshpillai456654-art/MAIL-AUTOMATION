"""
Deployment Tracker
==================
Tracks deployments across environments with a 6-state lifecycle.
Failed deployments can be rolled back; successful deployments can be
emergency-rolled-back.  Per-deployment notes provide an audit trail.

Tables:
  deployments       — deployment record
  deployment_notes  — append-only notes log

State machine:
  planned     → in_progress | cancelled
  in_progress → success | failed | cancelled
  failed      → rolled_back
  success     → rolled_back   (emergency rollback)
  rolled_back → (terminal)
  cancelled   → (terminal)

Auto-timestamps:
  started_at   set on → in_progress
  finished_at  set on → success | failed | cancelled
  rollback_at  set on → rolled_back

Endpoints:
  GET    /deployments
  POST   /deployments                           (201)
  GET    /deployments/stats
  GET    /deployments/{deployment_id}
  PATCH  /deployments/{deployment_id}
  DELETE /deployments/{deployment_id}
  POST   /deployments/{deployment_id}/transition
  GET    /deployments/{deployment_id}/notes
  POST   /deployments/{deployment_id}/notes     (201)
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
router = APIRouter(prefix="/deployments", tags=["deployments"])

_DB_PATH = str(Path(DATA_DIR) / "deployments.db")

_DEP_COLS = [
    "id", "name", "version", "environment", "status",
    "deployer", "service_id", "linked_change_id",
    "started_at", "finished_at", "rollback_at",
    "notes", "created_at", "updated_at",
]
_NOTE_COLS = ["id", "deployment_id", "note", "author", "created_at"]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "planned":     {"in_progress", "cancelled"},
    "in_progress": {"success", "failed", "cancelled"},
    "failed":      {"rolled_back"},
    "success":     {"rolled_back"},
    "rolled_back": set(),
    "cancelled":   set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS deployments (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            version          TEXT NOT NULL DEFAULT '',
            environment      TEXT NOT NULL DEFAULT 'production',
            status           TEXT NOT NULL DEFAULT 'planned',
            deployer         TEXT NOT NULL DEFAULT '',
            service_id       TEXT,
            linked_change_id TEXT,
            started_at       TEXT,
            finished_at      TEXT,
            rollback_at      TEXT,
            notes            TEXT NOT NULL DEFAULT '',
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deployment_notes (
            id            TEXT PRIMARY KEY,
            deployment_id TEXT NOT NULL,
            note          TEXT NOT NULL,
            author        TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_dep_status  ON deployments (status);
        CREATE INDEX IF NOT EXISTS idx_dep_env     ON deployments (environment);
        CREATE INDEX IF NOT EXISTS idx_dep_svc     ON deployments (service_id);
        CREATE INDEX IF NOT EXISTS idx_dnote_dep   ON deployment_notes (deployment_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_dep_or_404(con: sqlite3.Connection, deployment_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_DEP_COLS)} FROM deployments WHERE id=?",
        (deployment_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Deployment not found")
    return row


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class DeploymentCreate(BaseModel):
    name:             str
    version:          str           = ""
    environment:      str           = "production"
    deployer:         str           = ""
    service_id:       Optional[str] = None
    linked_change_id: Optional[str] = None
    notes:            str           = ""


class DeploymentPatch(BaseModel):
    name:             Optional[str] = None
    version:          Optional[str] = None
    environment:      Optional[str] = None
    deployer:         Optional[str] = None
    service_id:       Optional[str] = None
    linked_change_id: Optional[str] = None
    notes:            Optional[str] = None


class TransitionBody(BaseModel):
    status: str
    note:   str = ""
    author: str = ""


class NoteCreate(BaseModel):
    note:   str
    author: str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("", summary="List deployments")
async def list_deployments(
    q:           Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    environment: Optional[str] = Query(None),
    service_id:  Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(name LIKE ? OR version LIKE ? OR deployer LIKE ? OR environment LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if environment:
        where.append("environment = ?"); params.append(environment)
    if service_id:
        where.append("service_id = ?"); params.append(service_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(f"SELECT COUNT(*) FROM deployments {clause}", params).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_DEP_COLS)} FROM deployments {clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "deployments": [dict(zip(_DEP_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("", status_code=201, summary="Create deployment")
async def create_deployment(body: DeploymentCreate, _auth=Depends(require_local_auth)):
    dep_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO deployments ({','.join(_DEP_COLS)}) "
            f"VALUES ({','.join(['?']*len(_DEP_COLS))})",
            (dep_id, body.name, body.version, body.environment, "planned",
             body.deployer, body.service_id, body.linked_change_id,
             None, None, None, body.notes, now, now),
        )
        con.execute(
            f"INSERT INTO deployment_notes ({','.join(_NOTE_COLS)}) "
            f"VALUES ({','.join(['?']*len(_NOTE_COLS))})",
            (str(uuid.uuid4()), dep_id, "Deployment created.", body.deployer or "system", now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": dep_id, "name": body.name, "status": "planned"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Deployment statistics")
async def deployment_stats(_auth=Depends(require_local_auth)):
    try:
        con   = _conn()
        total = con.execute("SELECT COUNT(*) FROM deployments").fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM deployments GROUP BY status"
        ).fetchall()
        by_env = con.execute(
            "SELECT environment, COUNT(*) FROM deployments GROUP BY environment ORDER BY COUNT(*) DESC"
        ).fetchall()
        recent_failures = con.execute(
            "SELECT COUNT(*) FROM deployments WHERE status='failed' "
            "AND created_at >= datetime('now','-7 days')"
        ).fetchone()[0]
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total": total,
        "recent_failures": recent_failures,
        "by_status": [{"status": s, "count": c} for s, c in by_status],
        "by_env":    [{"environment": e, "count": c} for e, c in by_env],
    }


# ── Single deployment ─────────────────────────────────────────────────────────

@router.get("/{deployment_id}", summary="Get deployment")
async def get_deployment(deployment_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_dep_or_404(con, deployment_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_DEP_COLS, row))


@router.patch("/{deployment_id}", summary="Update deployment metadata")
async def patch_deployment(
    deployment_id: str, body: DeploymentPatch, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_dep_or_404(con, deployment_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "version", "environment", "deployer",
                      "service_id", "linked_change_id", "notes"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(deployment_id)
        con.execute(f"UPDATE deployments SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_DEP_COLS)} FROM deployments WHERE id=?",
            (deployment_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_DEP_COLS, row))


@router.delete("/{deployment_id}", status_code=204, summary="Delete deployment")
async def delete_deployment(deployment_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_dep_or_404(con, deployment_id)
        con.execute("DELETE FROM deployment_notes WHERE deployment_id=?", (deployment_id,))
        con.execute("DELETE FROM deployments WHERE id=?", (deployment_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/{deployment_id}/transition", summary="Transition deployment status")
async def transition_deployment(
    deployment_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}")
    try:
        con = _conn()
        row = _get_dep_or_404(con, deployment_id)
        d   = dict(zip(_DEP_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}")
        now = _now()
        sets   = ["status=?", "updated_at=?"]
        params = [body.status, now]
        if body.status == "in_progress" and not d["started_at"]:
            sets.append("started_at=?"); params.append(now)
        if body.status in {"success", "failed", "cancelled"} and not d["finished_at"]:
            sets.append("finished_at=?"); params.append(now)
        if body.status == "rolled_back":
            sets.append("rollback_at=?"); params.append(now)
        params.append(deployment_id)
        con.execute(f"UPDATE deployments SET {','.join(sets)} WHERE id=?", params)
        note_text = body.note or f"Status changed to {body.status}."
        con.execute(
            f"INSERT INTO deployment_notes ({','.join(_NOTE_COLS)}) "
            f"VALUES ({','.join(['?']*len(_NOTE_COLS))})",
            (str(uuid.uuid4()), deployment_id, note_text, body.author, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Notes ─────────────────────────────────────────────────────────────────────

@router.get("/{deployment_id}/notes", summary="List deployment notes")
async def list_notes(
    deployment_id: str,
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_dep_or_404(con, deployment_id)
        total = con.execute(
            "SELECT COUNT(*) FROM deployment_notes WHERE deployment_id=?",
            (deployment_id,),
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_NOTE_COLS)} FROM deployment_notes "
            "WHERE deployment_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (deployment_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "notes":  [dict(zip(_NOTE_COLS, r)) for r in rows],
        "total":  total,
    }


@router.post("/{deployment_id}/notes", status_code=201, summary="Add deployment note")
async def add_note(
    deployment_id: str, body: NoteCreate, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_dep_or_404(con, deployment_id)
        now = _now()
        note_id = str(uuid.uuid4())
        con.execute(
            f"INSERT INTO deployment_notes ({','.join(_NOTE_COLS)}) "
            f"VALUES ({','.join(['?']*len(_NOTE_COLS))})",
            (note_id, deployment_id, body.note, body.author, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": note_id, "ok": True}
