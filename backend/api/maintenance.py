"""
Maintenance Windows
===================
Schedule planned downtime windows that automatically suppress alerts, incident
creation, and SLA breach detection for the duration.

Status lifecycle:  scheduled → active → completed
                   scheduled → cancelled
                   active    → completed  (manual early-close)
                   active    → cancelled  (manual abort)

Background checker (30 s interval):
  - Activates scheduled windows whose starts_at <= now
  - Completes active windows whose ends_at <= now
  - Emits maintenance.started / maintenance.ended events

Public helpers (used by other modules):
  is_maintenance_active()  → bool
  get_active_window()      → dict | None

Tables:
  maintenance_windows  — window definitions
  maintenance_log      — lifecycle event log per window

Endpoints:
  GET    /maintenance
  POST   /maintenance               (201)
  GET    /maintenance/status
  GET    /maintenance/{window_id}   (with log)
  PATCH  /maintenance/{window_id}
  DELETE /maintenance/{window_id}
  POST   /maintenance/{window_id}/activate
  POST   /maintenance/{window_id}/complete
  POST   /maintenance/{window_id}/cancel
"""
from __future__ import annotations

import asyncio
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
router = APIRouter(prefix="/maintenance", tags=["maintenance"])

_DB_PATH  = str(Path(DATA_DIR) / "maintenance.db")
_running  = False
_checker  = None  # MaintenanceChecker instance

_WINDOW_COLS = [
    "id", "name", "description", "starts_at", "ends_at",
    "status", "created_by", "created_at", "updated_at",
    "suppress_alerts", "suppress_incidents", "suppress_sla",
]
_LOG_COLS = ["id", "window_id", "window_name", "event", "ts", "note"]

_VALID_TRANSITIONS = {
    "scheduled": {"active", "cancelled"},
    "active":    {"completed", "cancelled"},
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS maintenance_windows (
            id                 TEXT PRIMARY KEY,
            name               TEXT NOT NULL,
            description        TEXT NOT NULL DEFAULT '',
            starts_at          TEXT NOT NULL,
            ends_at            TEXT NOT NULL,
            status             TEXT NOT NULL DEFAULT 'scheduled',
            created_by         TEXT NOT NULL DEFAULT 'system',
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            suppress_alerts    INTEGER NOT NULL DEFAULT 1,
            suppress_incidents INTEGER NOT NULL DEFAULT 1,
            suppress_sla       INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS maintenance_log (
            id          TEXT PRIMARY KEY,
            window_id   TEXT NOT NULL,
            window_name TEXT NOT NULL,
            event       TEXT NOT NULL,
            ts          TEXT NOT NULL,
            note        TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_mw_status
            ON maintenance_windows (status, starts_at);
        CREATE INDEX IF NOT EXISTS idx_ml_window
            ON maintenance_log (window_id, ts DESC);
    """)
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Public helpers ────────────────────────────────────────────────────────────

def is_maintenance_active() -> bool:
    """Returns True if any window is currently active. Fast read for other modules."""
    try:
        con = _conn()
        row = con.execute(
            "SELECT id FROM maintenance_windows WHERE status='active' LIMIT 1"
        ).fetchone()
        con.close()
        return row is not None
    except Exception:
        return False


def get_active_window() -> Optional[dict]:
    """Returns the first active window dict, or None."""
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_WINDOW_COLS)} FROM maintenance_windows "
            "WHERE status='active' ORDER BY starts_at LIMIT 1"
        ).fetchone()
        con.close()
        return dict(zip(_WINDOW_COLS, row)) if row else None
    except Exception:
        return None


# ── Lifecycle helpers ─────────────────────────────────────────────────────────

def _add_log(window_id: str, window_name: str, event: str, note: str = "") -> None:
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO maintenance_log ({','.join(_LOG_COLS)}) VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), window_id, window_name, event, _now(), note),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.warning("Maintenance: log write failed: %s", exc)


async def _emit(event_type: str, window: dict) -> None:
    try:
        from backend.api.event_bus import get_event_bus
        await get_event_bus().publish({
            "type":       event_type,
            "severity":   "info",
            "source":     "maintenance_checker",
            "id":         str(uuid.uuid4()),
            "payload":    {
                "window_id":   window["id"],
                "window_name": window["name"],
                "starts_at":   window["starts_at"],
                "ends_at":     window["ends_at"],
            },
            "created_at": _now(),
        })
    except Exception as exc:
        logger.debug("Maintenance: event emit failed: %s", exc)


def _transition(window_id: str, new_status: str) -> Optional[dict]:
    """Applies status transition; returns updated window dict or None on failure."""
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_WINDOW_COLS)} FROM maintenance_windows WHERE id=?",
            (window_id,),
        ).fetchone()
        if not row:
            con.close()
            return None
        window = dict(zip(_WINDOW_COLS, row))
        allowed = _VALID_TRANSITIONS.get(window["status"], set())
        if new_status not in allowed:
            con.close()
            return None
        con.execute(
            "UPDATE maintenance_windows SET status=?, updated_at=? WHERE id=?",
            (new_status, _now(), window_id),
        )
        con.commit()
        con.close()
        window["status"] = new_status
        return window
    except Exception as exc:
        logger.warning("Maintenance: transition failed: %s", exc)
        return None


# ── Background checker ────────────────────────────────────────────────────────

async def _check_windows() -> None:
    now = _now()
    try:
        con = _conn()
        to_activate = con.execute(
            f"SELECT {','.join(_WINDOW_COLS)} FROM maintenance_windows "
            "WHERE status='scheduled' AND starts_at <= ?",
            (now,),
        ).fetchall()
        to_complete = con.execute(
            f"SELECT {','.join(_WINDOW_COLS)} FROM maintenance_windows "
            "WHERE status='active' AND ends_at <= ?",
            (now,),
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.debug("Maintenance: check failed: %s", exc)
        return

    for row in to_activate:
        window = dict(zip(_WINDOW_COLS, row))
        updated = _transition(window["id"], "active")
        if updated:
            _add_log(window["id"], window["name"], "activated", "Auto-activated by scheduler")
            await _emit("maintenance.started", updated)
            logger.info("Maintenance window '%s' activated", window["name"])

    for row in to_complete:
        window = dict(zip(_WINDOW_COLS, row))
        updated = _transition(window["id"], "completed")
        if updated:
            _add_log(window["id"], window["name"], "completed", "Auto-completed by scheduler")
            await _emit("maintenance.ended", updated)
            logger.info("Maintenance window '%s' completed", window["name"])


class MaintenanceChecker:
    INTERVAL_S = 30

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await _check_windows()
            except Exception as exc:
                logger.warning("Maintenance checker error: %s", exc)
            await asyncio.sleep(self.INTERVAL_S)


async def ensure_maintenance_running() -> None:
    global _running, _checker
    if _running:
        return
    _init_db()
    _running = True
    _checker = MaintenanceChecker()
    _checker.start()
    logger.info("Maintenance checker started")


def get_checker() -> Optional[MaintenanceChecker]:
    return _checker


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class WindowCreate(BaseModel):
    name:               str
    description:        str  = ""
    starts_at:          str
    ends_at:            str
    created_by:         str  = "system"
    suppress_alerts:    bool = True
    suppress_incidents: bool = True
    suppress_sla:       bool = True


class WindowPatch(BaseModel):
    name:               Optional[str]  = None
    description:        Optional[str]  = None
    starts_at:          Optional[str]  = None
    ends_at:            Optional[str]  = None
    suppress_alerts:    Optional[bool] = None
    suppress_incidents: Optional[bool] = None
    suppress_sla:       Optional[bool] = None


# ── Sub-routes before /{window_id} ────────────────────────────────────────────

@router.get("", summary="List maintenance windows")
async def list_windows(
    status: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if status:
        where.append("status = ?"); params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM maintenance_windows {clause}", params
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_WINDOW_COLS)} FROM maintenance_windows {clause} "
            "ORDER BY starts_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "windows": [dict(zip(_WINDOW_COLS, r)) for r in rows],
        "total":   total,
        "limit":   limit,
        "offset":  offset,
    }


@router.post("", status_code=201, summary="Create maintenance window")
async def create_window(body: WindowCreate, _auth=Depends(require_local_auth)):
    try:
        s = datetime.fromisoformat(body.starts_at)
        e = datetime.fromisoformat(body.ends_at)
    except ValueError:
        raise HTTPException(400, "starts_at and ends_at must be valid ISO 8601 timestamps")
    if e <= s:
        raise HTTPException(400, "ends_at must be after starts_at")
    win_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO maintenance_windows ({','.join(_WINDOW_COLS)}) "
            f"VALUES ({','.join(['?']*len(_WINDOW_COLS))})",
            (
                win_id, body.name, body.description, body.starts_at, body.ends_at,
                "scheduled", body.created_by, now, now,
                1 if body.suppress_alerts    else 0,
                1 if body.suppress_incidents else 0,
                1 if body.suppress_sla       else 0,
            ),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    _add_log(win_id, body.name, "created", f"Created by {body.created_by}")
    return {"id": win_id, "name": body.name}


@router.get("/status", summary="Current maintenance status")
async def maintenance_status(_auth=Depends(require_local_auth)):
    window = get_active_window()
    try:
        con = _conn()
        total     = con.execute("SELECT COUNT(*) FROM maintenance_windows").fetchone()[0]
        scheduled = con.execute("SELECT COUNT(*) FROM maintenance_windows WHERE status='scheduled'").fetchone()[0]
        active    = con.execute("SELECT COUNT(*) FROM maintenance_windows WHERE status='active'").fetchone()[0]
        completed = con.execute("SELECT COUNT(*) FROM maintenance_windows WHERE status='completed'").fetchone()[0]
        cancelled = con.execute("SELECT COUNT(*) FROM maintenance_windows WHERE status='cancelled'").fetchone()[0]
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "is_active":     window is not None,
        "active_window": window,
        "counts":        {"total": total, "scheduled": scheduled,
                          "active": active, "completed": completed, "cancelled": cancelled},
        "checker_running": _checker is not None and (
            _checker._task is not None and not _checker._task.done()
        ),
    }


# ── Window-specific routes ────────────────────────────────────────────────────

@router.get("/{window_id}", summary="Get maintenance window with log")
async def get_window(window_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_WINDOW_COLS)} FROM maintenance_windows WHERE id=?",
            (window_id,),
        ).fetchone()
        if not row:
            con.close()
            raise HTTPException(404, "Window not found")
        window = dict(zip(_WINDOW_COLS, row))
        log_rows = con.execute(
            f"SELECT {','.join(_LOG_COLS)} FROM maintenance_log "
            "WHERE window_id=? ORDER BY ts DESC LIMIT 50",
            (window_id,),
        ).fetchall()
        con.close()
        window["log"] = [dict(zip(_LOG_COLS, r)) for r in log_rows]
        return window
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.patch("/{window_id}", summary="Update maintenance window")
async def patch_window(
    window_id: str, body: WindowPatch, _auth=Depends(require_local_auth)
):
    updates, params = [], []
    if body.name is not None:
        updates.append("name = ?"); params.append(body.name)
    if body.description is not None:
        updates.append("description = ?"); params.append(body.description)
    if body.starts_at is not None:
        try:
            datetime.fromisoformat(body.starts_at)
        except ValueError:
            raise HTTPException(400, "Invalid starts_at")
        updates.append("starts_at = ?"); params.append(body.starts_at)
    if body.ends_at is not None:
        try:
            datetime.fromisoformat(body.ends_at)
        except ValueError:
            raise HTTPException(400, "Invalid ends_at")
        updates.append("ends_at = ?"); params.append(body.ends_at)
    if body.suppress_alerts is not None:
        updates.append("suppress_alerts = ?"); params.append(1 if body.suppress_alerts else 0)
    if body.suppress_incidents is not None:
        updates.append("suppress_incidents = ?"); params.append(1 if body.suppress_incidents else 0)
    if body.suppress_sla is not None:
        updates.append("suppress_sla = ?"); params.append(1 if body.suppress_sla else 0)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at = ?"); params.append(_now())
    params.append(window_id)
    try:
        con = _conn()
        con.execute(f"UPDATE maintenance_windows SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "Window not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


@router.delete("/{window_id}", status_code=204, summary="Delete maintenance window")
async def delete_window(window_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            "SELECT status FROM maintenance_windows WHERE id=?", (window_id,)
        ).fetchone()
        if not row:
            con.close()
            raise HTTPException(404, "Window not found")
        if row[0] == "active":
            con.close()
            raise HTTPException(409, "Cannot delete an active window — cancel it first")
        con.execute("DELETE FROM maintenance_log WHERE window_id=?", (window_id,))
        con.execute("DELETE FROM maintenance_windows WHERE id=?", (window_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/{window_id}/activate", summary="Manually activate a scheduled window")
async def activate_window(window_id: str, _auth=Depends(require_local_auth)):
    window = _transition(window_id, "active")
    if window is None:
        con = _conn()
        exists = con.execute(
            "SELECT status FROM maintenance_windows WHERE id=?", (window_id,)
        ).fetchone()
        con.close()
        if not exists:
            raise HTTPException(404, "Window not found")
        raise HTTPException(409, f"Cannot activate window in status '{exists[0]}'")
    _add_log(window_id, window["name"], "activated", "Manually activated")
    await _emit("maintenance.started", window)
    return {"ok": True, "status": "active"}


@router.post("/{window_id}/complete", summary="Manually complete an active window")
async def complete_window(window_id: str, _auth=Depends(require_local_auth)):
    window = _transition(window_id, "completed")
    if window is None:
        con = _conn()
        exists = con.execute(
            "SELECT status FROM maintenance_windows WHERE id=?", (window_id,)
        ).fetchone()
        con.close()
        if not exists:
            raise HTTPException(404, "Window not found")
        raise HTTPException(409, f"Cannot complete window in status '{exists[0]}'")
    _add_log(window_id, window["name"], "completed", "Manually completed")
    await _emit("maintenance.ended", window)
    return {"ok": True, "status": "completed"}


@router.post("/{window_id}/cancel", summary="Cancel a scheduled or active window")
async def cancel_window(window_id: str, _auth=Depends(require_local_auth)):
    window = _transition(window_id, "cancelled")
    if window is None:
        con = _conn()
        exists = con.execute(
            "SELECT status FROM maintenance_windows WHERE id=?", (window_id,)
        ).fetchone()
        con.close()
        if not exists:
            raise HTTPException(404, "Window not found")
        raise HTTPException(409, f"Cannot cancel window in status '{exists[0]}'")
    _add_log(window_id, window["name"], "cancelled", "Manually cancelled")
    await _emit("maintenance.cancelled", window)
    return {"ok": True, "status": "cancelled"}
