"""
Problem Management
==================
ITIL-style root cause analysis records linked to incidents.
Problems represent recurring or systemic issues; resolving them
prevents future incidents rather than just restoring service.

Tables:
  problems           — the problem record (title, status, priority, root cause, workaround)
  problem_incidents  — M:M link between problems and incident IDs
  problem_timeline   — immutable activity log per problem

State machine:
  open → investigating | closed
  investigating → known_error | resolved | open
  known_error → resolved
  resolved → closed | open (re-opened)
  closed → (terminal)

Endpoints:
  GET    /problems
  POST   /problems                             (201)
  GET    /problems/stats
  GET    /problems/{problem_id}
  PATCH  /problems/{problem_id}
  DELETE /problems/{problem_id}
  POST   /problems/{problem_id}/transition
  GET    /problems/{problem_id}/incidents
  POST   /problems/{problem_id}/incidents      (201)
  DELETE /problems/{problem_id}/incidents/{incident_id}
  GET    /problems/{problem_id}/timeline
  POST   /problems/{problem_id}/timeline       (201)
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
router = APIRouter(prefix="/problems", tags=["problem_management"])

_DB_PATH = str(Path(DATA_DIR) / "problem_management.db")

_PR_COLS = [
    "id", "title", "description", "status", "priority", "category",
    "owner", "assignee", "root_cause", "workaround",
    "linked_change_id", "created_at", "updated_at", "resolved_at",
]
_TL_COLS = ["id", "problem_id", "event_type", "note", "author", "created_at"]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "open":          {"investigating", "closed"},
    "investigating": {"known_error", "resolved", "open"},
    "known_error":   {"resolved"},
    "resolved":      {"closed", "open"},
    "closed":        set(),
}
_VALID_STATUSES  = set(_VALID_TRANSITIONS.keys())
_VALID_PRIORITIES = {"low", "medium", "high", "critical"}
_VALID_EVENT_TYPES = {
    "note", "status_change", "linked_incident", "unlinked_incident",
    "root_cause_updated", "workaround_updated",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS problems (
            id               TEXT PRIMARY KEY,
            title            TEXT NOT NULL,
            description      TEXT NOT NULL DEFAULT '',
            status           TEXT NOT NULL DEFAULT 'open',
            priority         TEXT NOT NULL DEFAULT 'medium',
            category         TEXT NOT NULL DEFAULT '',
            owner            TEXT NOT NULL DEFAULT '',
            assignee         TEXT NOT NULL DEFAULT '',
            root_cause       TEXT NOT NULL DEFAULT '',
            workaround       TEXT NOT NULL DEFAULT '',
            linked_change_id TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            resolved_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS problem_incidents (
            id          TEXT PRIMARY KEY,
            problem_id  TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            note        TEXT NOT NULL DEFAULT '',
            linked_at   TEXT NOT NULL,
            UNIQUE (problem_id, incident_id)
        );

        CREATE TABLE IF NOT EXISTS problem_timeline (
            id         TEXT PRIMARY KEY,
            problem_id TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'note',
            note       TEXT NOT NULL DEFAULT '',
            author     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pr_status
            ON problems (status);
        CREATE INDEX IF NOT EXISTS idx_pr_priority
            ON problems (priority);
        CREATE INDEX IF NOT EXISTS idx_pr_category
            ON problems (category);
        CREATE INDEX IF NOT EXISTS idx_pr_owner
            ON problems (owner);
        CREATE INDEX IF NOT EXISTS idx_pr_assignee
            ON problems (assignee);
        CREATE INDEX IF NOT EXISTS idx_pi_problem
            ON problem_incidents (problem_id);
        CREATE INDEX IF NOT EXISTS idx_tl_problem
            ON problem_timeline (problem_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_problem_or_404(con: sqlite3.Connection, problem_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_PR_COLS)} FROM problems WHERE id=?", (problem_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Problem not found")
    return row


def _add_timeline(con: sqlite3.Connection, problem_id: str,
                  event_type: str, note: str, author: str) -> None:
    con.execute(
        f"INSERT INTO problem_timeline ({','.join(_TL_COLS)}) "
        f"VALUES ({','.join(['?']*len(_TL_COLS))})",
        (str(uuid.uuid4()), problem_id, event_type, note, author, _now()),
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ProblemCreate(BaseModel):
    title:           str
    description:     str           = ""
    priority:        str           = "medium"
    category:        str           = ""
    owner:           str           = ""
    assignee:        str           = ""
    root_cause:      str           = ""
    workaround:      str           = ""
    linked_change_id: Optional[str] = None


class ProblemPatch(BaseModel):
    title:           Optional[str] = None
    description:     Optional[str] = None
    priority:        Optional[str] = None
    category:        Optional[str] = None
    owner:           Optional[str] = None
    assignee:        Optional[str] = None
    root_cause:      Optional[str] = None
    workaround:      Optional[str] = None
    linked_change_id: Optional[str] = None
    author:          str           = ""


class TransitionBody(BaseModel):
    status: str
    note:   str = ""
    author: str = ""


class LinkIncidentBody(BaseModel):
    incident_id: str
    note:        str = ""
    author:      str = ""


class TimelineEntry(BaseModel):
    event_type: str = "note"
    note:       str
    author:     str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("", summary="List problems")
async def list_problems(
    q:        Optional[str] = Query(None),
    status:   Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit:    int = Query(50, ge=1, le=500),
    offset:   int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(title LIKE ? OR description LIKE ? OR root_cause LIKE ? OR workaround LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if priority:
        where.append("priority = ?"); params.append(priority)
    if category:
        where.append("category = ?"); params.append(category)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(f"SELECT COUNT(*) FROM problems {clause}", params).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_PR_COLS)} FROM problems {clause} "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "problems": [dict(zip(_PR_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("", status_code=201, summary="Create problem record")
async def create_problem(body: ProblemCreate, _auth=Depends(require_local_auth)):
    if body.priority not in _VALID_PRIORITIES:
        raise HTTPException(400, f"priority must be one of {sorted(_VALID_PRIORITIES)}")
    pr_id = str(uuid.uuid4())
    now   = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO problems ({','.join(_PR_COLS)}) "
            f"VALUES ({','.join(['?']*len(_PR_COLS))})",
            (pr_id, body.title, body.description, "open", body.priority,
             body.category, body.owner, body.assignee,
             body.root_cause, body.workaround, body.linked_change_id,
             now, now, None),
        )
        _add_timeline(con, pr_id, "note", "Problem record created.", body.owner or "system")
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": pr_id, "title": body.title, "status": "open"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Problem statistics")
async def problem_stats(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        total      = con.execute("SELECT COUNT(*) FROM problems").fetchone()[0]
        by_status  = con.execute("SELECT status, COUNT(*) FROM problems GROUP BY status").fetchall()
        by_priority = con.execute("SELECT priority, COUNT(*) FROM problems GROUP BY priority").fetchall()
        open_count = con.execute("SELECT COUNT(*) FROM problems WHERE status NOT IN ('closed','resolved')").fetchone()[0]
        linked     = con.execute("SELECT COUNT(*) FROM problem_incidents").fetchone()[0]
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":       total,
        "open":        open_count,
        "linked_incidents": linked,
        "by_status":   [{"status": r[0], "count": r[1]} for r in by_status],
        "by_priority": [{"priority": r[0], "count": r[1]} for r in by_priority],
    }


# ── Problem detail / patch / delete / transition ──────────────────────────────

@router.get("/{problem_id}", summary="Problem detail")
async def get_problem(problem_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_problem_or_404(con, problem_id)
        inc_rows = con.execute(
            "SELECT id, problem_id, incident_id, note, linked_at "
            "FROM problem_incidents WHERE problem_id=? ORDER BY linked_at LIMIT 100",
            (problem_id,),
        ).fetchall()
        tl_rows = con.execute(
            f"SELECT {','.join(_TL_COLS)} FROM problem_timeline "
            "WHERE problem_id=? ORDER BY created_at DESC LIMIT 20",
            (problem_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    pr = dict(zip(_PR_COLS, row))
    pr["linked_incidents"] = [
        dict(zip(["id", "problem_id", "incident_id", "note", "linked_at"], r))
        for r in inc_rows
    ]
    pr["recent_timeline"] = [dict(zip(_TL_COLS, r)) for r in tl_rows]
    return pr


@router.patch("/{problem_id}", summary="Update problem fields")
async def patch_problem(problem_id: str, body: ProblemPatch,
                        _auth=Depends(require_local_auth)):
    updates, params = [], []
    tracked_changes = []

    for field in ["title", "description", "category", "owner", "assignee", "linked_change_id"]:
        val = getattr(body, field)
        if val is not None:
            updates.append(f"{field} = ?"); params.append(val)

    if body.priority is not None:
        if body.priority not in _VALID_PRIORITIES:
            raise HTTPException(400, f"priority must be one of {sorted(_VALID_PRIORITIES)}")
        updates.append("priority = ?"); params.append(body.priority)

    if body.root_cause is not None:
        updates.append("root_cause = ?"); params.append(body.root_cause)
        tracked_changes.append("root_cause_updated")

    if body.workaround is not None:
        updates.append("workaround = ?"); params.append(body.workaround)
        tracked_changes.append("workaround_updated")

    if not updates:
        raise HTTPException(400, "No fields to update")

    updates.append("updated_at = ?"); params.append(_now())
    params.append(problem_id)
    try:
        con = _conn()
        con.execute(f"UPDATE problems SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close(); raise HTTPException(404, "Problem not found")
        for ev in tracked_changes:
            _add_timeline(con, problem_id, ev, f"{ev.replace('_', ' ').title()}.", body.author or "system")
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


@router.delete("/{problem_id}", status_code=204, summary="Delete problem")
async def delete_problem(problem_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute("SELECT id FROM problems WHERE id=?", (problem_id,)).fetchone()
        if not row:
            con.close(); raise HTTPException(404, "Problem not found")
        con.execute("DELETE FROM problem_incidents WHERE problem_id=?", (problem_id,))
        con.execute("DELETE FROM problem_timeline WHERE problem_id=?", (problem_id,))
        con.execute("DELETE FROM problems WHERE id=?", (problem_id,))
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/{problem_id}/transition", summary="Transition problem status")
async def transition_problem(problem_id: str, body: TransitionBody,
                             _auth=Depends(require_local_auth)):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(400, f"Unknown status '{body.status}'")
    try:
        con = _conn()
        row = _get_problem_or_404(con, problem_id)
        pr  = dict(zip(_PR_COLS, row))
        allowed = _VALID_TRANSITIONS.get(pr["status"], set())
        if body.status not in allowed:
            con.close()
            raise HTTPException(400,
                f"Cannot transition '{pr['status']}' → '{body.status}'. "
                f"Allowed: {sorted(allowed) or 'none (terminal)'}")
        now = _now()
        resolved_at = now if body.status in ("resolved", "closed") and not pr["resolved_at"] else pr["resolved_at"]
        if body.status == "open" and pr["status"] == "resolved":
            resolved_at = None
        con.execute(
            "UPDATE problems SET status=?, updated_at=?, resolved_at=? WHERE id=?",
            (body.status, now, resolved_at, problem_id),
        )
        _add_timeline(con, problem_id, "status_change",
                      f"Status changed to '{body.status}'. {body.note}".strip(),
                      body.author or "system")
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Linked incidents ──────────────────────────────────────────────────────────

@router.get("/{problem_id}/incidents", summary="Incidents linked to this problem")
async def list_linked_incidents(problem_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_problem_or_404(con, problem_id)
        rows = con.execute(
            "SELECT id, problem_id, incident_id, note, linked_at "
            "FROM problem_incidents WHERE problem_id=? ORDER BY linked_at LIMIT 100",
            (problem_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    cols = ["id", "problem_id", "incident_id", "note", "linked_at"]
    return {"incidents": [dict(zip(cols, r)) for r in rows]}


@router.post("/{problem_id}/incidents", status_code=201, summary="Link an incident")
async def link_incident(problem_id: str, body: LinkIncidentBody,
                        _auth=Depends(require_local_auth)):
    if not body.incident_id.strip():
        raise HTTPException(400, "incident_id is required")
    link_id = str(uuid.uuid4())
    now = _now()
    try:
        con = _conn()
        _get_problem_or_404(con, problem_id)
        con.execute(
            "INSERT INTO problem_incidents (id, problem_id, incident_id, note, linked_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (link_id, problem_id, body.incident_id, body.note, now),
        )
        _add_timeline(con, problem_id, "linked_incident",
                      f"Linked incident {body.incident_id}. {body.note}".strip(),
                      body.author or "system")
        con.execute("UPDATE problems SET updated_at=? WHERE id=?", (now, problem_id))
        con.commit(); con.close()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Incident '{body.incident_id}' already linked")
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": link_id, "incident_id": body.incident_id}


@router.delete("/{problem_id}/incidents/{incident_id}", status_code=204,
               summary="Unlink an incident")
async def unlink_incident(problem_id: str, incident_id: str,
                          _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_problem_or_404(con, problem_id)
        con.execute(
            "DELETE FROM problem_incidents WHERE problem_id=? AND incident_id=?",
            (problem_id, incident_id),
        )
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close(); raise HTTPException(404, "Linked incident not found")
        now = _now()
        _add_timeline(con, problem_id, "unlinked_incident",
                      f"Unlinked incident {incident_id}.", "system")
        con.execute("UPDATE problems SET updated_at=? WHERE id=?", (now, problem_id))
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Timeline ──────────────────────────────────────────────────────────────────

@router.get("/{problem_id}/timeline", summary="Full activity timeline")
async def get_timeline(
    problem_id: str,
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_problem_or_404(con, problem_id)
        total = con.execute(
            "SELECT COUNT(*) FROM problem_timeline WHERE problem_id=?", (problem_id,)
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_TL_COLS)} FROM problem_timeline "
            "WHERE problem_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (problem_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "timeline": [dict(zip(_TL_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("/{problem_id}/timeline", status_code=201, summary="Add timeline entry")
async def add_timeline_entry(problem_id: str, body: TimelineEntry,
                             _auth=Depends(require_local_auth)):
    if body.event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(400, f"event_type must be one of {sorted(_VALID_EVENT_TYPES)}")
    if not body.note.strip():
        raise HTTPException(400, "note is required")
    entry_id = str(uuid.uuid4())
    now = _now()
    try:
        con = _conn()
        _get_problem_or_404(con, problem_id)
        con.execute(
            f"INSERT INTO problem_timeline ({','.join(_TL_COLS)}) "
            f"VALUES ({','.join(['?']*len(_TL_COLS))})",
            (entry_id, problem_id, body.event_type, body.note, body.author or "system", now),
        )
        con.execute("UPDATE problems SET updated_at=? WHERE id=?", (now, problem_id))
        con.commit(); con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": entry_id, "event_type": body.event_type, "created_at": now}
