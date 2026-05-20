"""
On-call Schedule Manager
========================
Define named schedules with rotation slots and per-schedule escalation policies.
An escalation engine fires every 60 s and emits oncall.escalated events for open
incidents that have not been acknowledged within the configured delay.

Tables:
  oncall_schedules     — named schedules (timezone, enabled)
  oncall_slots         — who is on call during a time window; is_override flag
                         lets one-off coverage override the regular rotation
  oncall_escalations   — ordered tiers (level 1 = first responder, level 2 = backup …)
                         each with delay_minutes measured from incident creation
  oncall_notifications — idempotency log: (incident_id, level) UNIQUE so each
                         escalation tier fires at most once per incident

Public helpers:
  get_current_oncall(schedule_id=None) → list[dict]
    Returns the currently-active slot(s); pass schedule_id to narrow to one schedule.

Background escalation (60 s loop):
  - Loads open incidents from the incidents DB
  - For each enabled schedule with escalation policies, walks tiers in level order
  - Emits oncall.escalated when elapsed_minutes >= delay_minutes (idempotent)

Endpoints:
  GET    /oncall/schedules
  POST   /oncall/schedules               (201)
  GET    /oncall/schedules/current
  GET    /oncall/schedules/{schedule_id}
  PATCH  /oncall/schedules/{schedule_id}
  DELETE /oncall/schedules/{schedule_id}
  POST   /oncall/slots                   (201)
  DELETE /oncall/slots/{slot_id}
  POST   /oncall/escalations             (201)
  DELETE /oncall/escalations/{esc_id}
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/oncall", tags=["oncall"])

_DB_PATH = str(Path(DATA_DIR) / "oncall.db")
_running = False
_checker = None

_SCH_COLS = [
    "id", "name", "description", "timezone", "enabled", "created_at", "updated_at",
]
_SLOT_COLS = [
    "id", "schedule_id", "schedule_name", "member_name", "member_email",
    "starts_at", "ends_at", "is_override", "note", "created_at",
]
_ESC_COLS = [
    "id", "schedule_id", "level", "contact_name", "contact_email",
    "notify_via", "delay_minutes", "created_at",
]
_NOTIF_COLS = [
    "id", "incident_id", "schedule_id", "escalation_id",
    "level", "notified_at", "contact_name", "contact_email",
]


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS oncall_schedules (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            timezone    TEXT NOT NULL DEFAULT 'UTC',
            enabled     INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS oncall_slots (
            id            TEXT PRIMARY KEY,
            schedule_id   TEXT NOT NULL,
            schedule_name TEXT NOT NULL,
            member_name   TEXT NOT NULL,
            member_email  TEXT NOT NULL DEFAULT '',
            starts_at     TEXT NOT NULL,
            ends_at       TEXT NOT NULL,
            is_override   INTEGER NOT NULL DEFAULT 0,
            note          TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS oncall_escalations (
            id            TEXT PRIMARY KEY,
            schedule_id   TEXT NOT NULL,
            level         INTEGER NOT NULL,
            contact_name  TEXT NOT NULL,
            contact_email TEXT NOT NULL DEFAULT '',
            notify_via    TEXT NOT NULL DEFAULT 'event',
            delay_minutes INTEGER NOT NULL DEFAULT 15,
            created_at    TEXT NOT NULL,
            UNIQUE (schedule_id, level)
        );

        CREATE TABLE IF NOT EXISTS oncall_notifications (
            id            TEXT PRIMARY KEY,
            incident_id   TEXT NOT NULL,
            schedule_id   TEXT NOT NULL,
            escalation_id TEXT NOT NULL,
            level         INTEGER NOT NULL,
            notified_at   TEXT NOT NULL,
            contact_name  TEXT NOT NULL,
            contact_email TEXT NOT NULL DEFAULT '',
            UNIQUE (incident_id, schedule_id, level)
        );

        CREATE INDEX IF NOT EXISTS idx_slots_time
            ON oncall_slots (starts_at, ends_at);
        CREATE INDEX IF NOT EXISTS idx_esc_schedule
            ON oncall_escalations (schedule_id, level);
        CREATE INDEX IF NOT EXISTS idx_notif_incident
            ON oncall_notifications (incident_id, schedule_id);
    """)
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minutes_elapsed(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 60
    except Exception:
        return 0.0


# ── Public helpers ────────────────────────────────────────────────────────────

def get_current_oncall(schedule_id: Optional[str] = None) -> list[dict]:
    """Returns currently active slots (is_override takes priority)."""
    now = _now()
    try:
        con = _conn()
        params: list = [now, now]
        where = "starts_at <= ? AND ends_at > ?"
        if schedule_id:
            where += " AND schedule_id = ?"
            params.append(schedule_id)
        rows = con.execute(
            f"SELECT {','.join(_SLOT_COLS)} FROM oncall_slots "
            f"WHERE {where} ORDER BY is_override DESC, starts_at ASC",
            params,
        ).fetchall()
        con.close()
        return [dict(zip(_SLOT_COLS, r)) for r in rows]
    except Exception as exc:
        logger.debug("On-call: current lookup failed: %s", exc)
        return []


# ── Escalation engine ─────────────────────────────────────────────────────────

def _get_open_incidents() -> list[dict]:
    try:
        from backend.api.incidents import _DB_PATH as inc_db
        con = sqlite3.connect(inc_db, timeout=5)
        rows = con.execute(
            "SELECT id, title, severity, created_at FROM incidents "
            "WHERE status IN ('open','acknowledged')"
        ).fetchall()
        con.close()
        return [{"id": r[0], "title": r[1], "severity": r[2], "created_at": r[3]}
                for r in rows]
    except Exception as exc:
        logger.debug("On-call: incidents fetch failed: %s", exc)
        return []


async def _emit_escalation(schedule: dict, esc: dict, incident: dict) -> None:
    try:
        from backend.api.event_bus import get_event_bus
        await get_event_bus().publish({
            "type":       "oncall.escalated",
            "severity":   "high",
            "source":     "oncall_engine",
            "id":         str(uuid.uuid4()),
            "payload": {
                "schedule_id":    schedule["id"],
                "schedule_name":  schedule["name"],
                "level":          esc["level"],
                "contact_name":   esc["contact_name"],
                "contact_email":  esc["contact_email"],
                "incident_id":    incident["id"],
                "incident_title": incident["title"],
                "delay_minutes":  esc["delay_minutes"],
            },
            "created_at": _now(),
        })
    except Exception as exc:
        logger.debug("On-call: escalation event failed: %s", exc)


def _record_notification(incident_id: str, schedule_id: str,
                          esc: dict) -> bool:
    """Inserts notification record; returns True if new (not a duplicate)."""
    try:
        con = _conn()
        cur = con.execute(
            f"INSERT OR IGNORE INTO oncall_notifications ({','.join(_NOTIF_COLS)}) "
            f"VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), incident_id, schedule_id, esc["id"],
             esc["level"], _now(), esc["contact_name"], esc["contact_email"]),
        )
        inserted = cur.rowcount > 0
        con.commit()
        con.close()
        return inserted
    except Exception as exc:
        logger.warning("On-call: notification record failed: %s", exc)
        return False


async def _run_escalations() -> None:
    incidents = _get_open_incidents()
    if not incidents:
        return
    try:
        con = _conn()
        schedules = con.execute(
            f"SELECT {','.join(_SCH_COLS)} FROM oncall_schedules WHERE enabled=1"
        ).fetchall()
        con.close()
    except Exception:
        return

    for sch_row in schedules:
        schedule = dict(zip(_SCH_COLS, sch_row))
        try:
            con = _conn()
            esc_rows = con.execute(
                f"SELECT {','.join(_ESC_COLS)} FROM oncall_escalations "
                "WHERE schedule_id=? ORDER BY level ASC",
                (schedule["id"],),
            ).fetchall()
            con.close()
        except Exception:
            continue

        escalations = [dict(zip(_ESC_COLS, r)) for r in esc_rows]
        if not escalations:
            continue

        for incident in incidents:
            elapsed = _minutes_elapsed(incident["created_at"])
            for esc in escalations:
                if elapsed >= esc["delay_minutes"]:
                    if _record_notification(incident["id"], schedule["id"], esc):
                        await _emit_escalation(schedule, esc, incident)


class OncallChecker:
    INTERVAL_S = 60

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
                await _run_escalations()
            except Exception as exc:
                logger.warning("On-call checker error: %s", exc)
            await asyncio.sleep(self.INTERVAL_S)


async def ensure_oncall_running() -> None:
    global _running, _checker
    if _running:
        return
    if not get_runtime_control().is_service_enabled("oncall"):
        logger.info("On-call escalation engine disabled by runtime policy")
        return
    _init_db()
    _running = True
    _checker = OncallChecker()
    _checker.start()
    logger.info("On-call escalation engine started")


def get_checker() -> Optional[OncallChecker]:
    return _checker


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    name:        str
    description: str  = ""
    timezone:    str  = "UTC"
    enabled:     bool = True


class SchedulePatch(BaseModel):
    name:        Optional[str]  = None
    description: Optional[str]  = None
    timezone:    Optional[str]  = None
    enabled:     Optional[bool] = None


class SlotCreate(BaseModel):
    schedule_id:  str
    member_name:  str
    member_email: str  = ""
    starts_at:    str
    ends_at:      str
    is_override:  bool = False
    note:         str  = ""


class EscalationCreate(BaseModel):
    schedule_id:   str
    level:         int
    contact_name:  str
    contact_email: str = ""
    notify_via:    str = "event"
    delay_minutes: int = 15


# ── Sub-routes before /{schedule_id} ─────────────────────────────────────────

@router.get("/schedules", summary="List on-call schedules")
async def list_schedules(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        rows = con.execute(
            f"SELECT {','.join(_SCH_COLS)} FROM oncall_schedules ORDER BY created_at DESC"
        ).fetchall()
        con.close()
    except Exception:
        return {"schedules": []}
    return {"schedules": [dict(zip(_SCH_COLS, r)) for r in rows]}


@router.post("/schedules", status_code=201, summary="Create on-call schedule")
async def create_schedule(body: ScheduleCreate, _auth=Depends(require_local_auth)):
    sch_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO oncall_schedules ({','.join(_SCH_COLS)}) "
            f"VALUES ({','.join(['?']*len(_SCH_COLS))})",
            (sch_id, body.name, body.description, body.timezone,
             1 if body.enabled else 0, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": sch_id, "name": body.name}


@router.get("/schedules/current", summary="Who is on call right now")
async def current_oncall(_auth=Depends(require_local_auth)):
    slots = get_current_oncall()
    by_schedule: dict[str, list] = {}
    for slot in slots:
        by_schedule.setdefault(slot["schedule_name"], []).append(slot)
    return {"on_call": slots, "by_schedule": by_schedule, "count": len(slots)}


# ── Schedule-specific routes ──────────────────────────────────────────────────

@router.get("/schedules/{schedule_id}", summary="Schedule detail with slots and escalations")
async def get_schedule(schedule_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_SCH_COLS)} FROM oncall_schedules WHERE id=?",
            (schedule_id,),
        ).fetchone()
        if not row:
            con.close()
            raise HTTPException(404, "Schedule not found")
        schedule = dict(zip(_SCH_COLS, row))
        now = _now()
        slots = con.execute(
            f"SELECT {','.join(_SLOT_COLS)} FROM oncall_slots "
            "WHERE schedule_id=? AND ends_at > ? ORDER BY starts_at ASC LIMIT 50",
            (schedule_id, now),
        ).fetchall()
        escalations = con.execute(
            f"SELECT {','.join(_ESC_COLS)} FROM oncall_escalations "
            "WHERE schedule_id=? ORDER BY level ASC",
            (schedule_id,),
        ).fetchall()
        con.close()
        schedule["upcoming_slots"] = [dict(zip(_SLOT_COLS, r)) for r in slots]
        schedule["escalation_policy"] = [dict(zip(_ESC_COLS, r)) for r in escalations]
        schedule["current_oncall"] = get_current_oncall(schedule_id)
        return schedule
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.patch("/schedules/{schedule_id}", summary="Update schedule")
async def patch_schedule(
    schedule_id: str, body: SchedulePatch, _auth=Depends(require_local_auth)
):
    updates, params = [], []
    if body.name is not None:
        updates.append("name = ?"); params.append(body.name)
    if body.description is not None:
        updates.append("description = ?"); params.append(body.description)
    if body.timezone is not None:
        updates.append("timezone = ?"); params.append(body.timezone)
    if body.enabled is not None:
        updates.append("enabled = ?"); params.append(1 if body.enabled else 0)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at = ?"); params.append(_now())
    params.append(schedule_id)
    try:
        con = _conn()
        con.execute(f"UPDATE oncall_schedules SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "Schedule not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


@router.delete("/schedules/{schedule_id}", status_code=204, summary="Delete schedule")
async def delete_schedule(schedule_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM oncall_notifications WHERE schedule_id=?", (schedule_id,))
        con.execute("DELETE FROM oncall_escalations WHERE schedule_id=?", (schedule_id,))
        con.execute("DELETE FROM oncall_slots WHERE schedule_id=?", (schedule_id,))
        con.execute("DELETE FROM oncall_schedules WHERE id=?", (schedule_id,))
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Slot routes ───────────────────────────────────────────────────────────────

@router.post("/slots", status_code=201, summary="Add rotation slot")
async def create_slot(body: SlotCreate, _auth=Depends(require_local_auth)):
    try:
        s = datetime.fromisoformat(body.starts_at)
        e = datetime.fromisoformat(body.ends_at)
    except ValueError:
        raise HTTPException(400, "starts_at and ends_at must be valid ISO 8601")
    if e <= s:
        raise HTTPException(400, "ends_at must be after starts_at")
    try:
        con = _conn()
        name_row = con.execute(
            "SELECT name FROM oncall_schedules WHERE id=?", (body.schedule_id,)
        ).fetchone()
        if not name_row:
            con.close()
            raise HTTPException(404, "Schedule not found")
        slot_id = str(uuid.uuid4())
        now = _now()
        con.execute(
            f"INSERT INTO oncall_slots ({','.join(_SLOT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_SLOT_COLS))})",
            (slot_id, body.schedule_id, name_row[0], body.member_name,
             body.member_email, body.starts_at, body.ends_at,
             1 if body.is_override else 0, body.note, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": slot_id, "member_name": body.member_name}


@router.delete("/slots/{slot_id}", status_code=204, summary="Remove rotation slot")
async def delete_slot(slot_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM oncall_slots WHERE id=?", (slot_id,))
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Escalation routes ─────────────────────────────────────────────────────────

@router.post("/escalations", status_code=201, summary="Add escalation tier")
async def create_escalation(body: EscalationCreate, _auth=Depends(require_local_auth)):
    if body.level < 1:
        raise HTTPException(400, "level must be >= 1")
    if body.delay_minutes < 1:
        raise HTTPException(400, "delay_minutes must be >= 1")
    try:
        con = _conn()
        exists = con.execute(
            "SELECT id FROM oncall_schedules WHERE id=?", (body.schedule_id,)
        ).fetchone()
        if not exists:
            con.close()
            raise HTTPException(404, "Schedule not found")
        esc_id = str(uuid.uuid4())
        con.execute(
            f"INSERT INTO oncall_escalations ({','.join(_ESC_COLS)}) "
            f"VALUES ({','.join(['?']*len(_ESC_COLS))})",
            (esc_id, body.schedule_id, body.level, body.contact_name,
             body.contact_email, body.notify_via, body.delay_minutes, _now()),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Level {body.level} already exists for this schedule")
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": esc_id, "level": body.level, "contact_name": body.contact_name}


@router.delete("/escalations/{esc_id}", status_code=204, summary="Remove escalation tier")
async def delete_escalation(esc_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM oncall_escalations WHERE id=?", (esc_id,))
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
