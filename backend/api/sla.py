"""
SLA Management
==============
Define SLA policies (response + resolution time limits per severity) and
automatically detect breaches against open incidents.

A policy maps to a severity level (or '' = all severities) and sets two
time limits measured from incident creation:
  response_minutes  — time allowed before the incident must be acknowledged
  resolve_minutes   — time allowed before the incident must be resolved

Background checker (60 s interval):
  - Queries the incidents DB for open / acknowledged incidents
  - Compares elapsed time against every active policy whose severity matches
  - Inserts breach records (idempotent via UNIQUE constraint) and emits
    sla.breach events on first detection

Endpoints:
  GET    /sla/policies
  POST   /sla/policies          (201)
  GET    /sla/policies/stats
  GET    /sla/policies/{policy_id}
  PATCH  /sla/policies/{policy_id}
  DELETE /sla/policies/{policy_id}
  GET    /sla/breaches
  GET    /sla/status
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sla", tags=["sla"])

_DB_PATH = str(Path(DATA_DIR) / "sla.db")
_running = False
_checker = None  # SlaChecker instance, set by ensure_sla_running()

_POLICY_COLS = [
    "id", "name", "severity", "response_minutes", "resolve_minutes",
    "enabled", "created_at", "updated_at",
]
_BREACH_COLS = [
    "id", "policy_id", "policy_name", "incident_id", "incident_title",
    "incident_severity", "breach_type", "breached_at", "notified", "created_at",
]


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS sla_policies (
            id               TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            severity         TEXT NOT NULL DEFAULT '',
            response_minutes INTEGER NOT NULL DEFAULT 60,
            resolve_minutes  INTEGER NOT NULL DEFAULT 240,
            enabled          INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sla_breaches (
            id               TEXT PRIMARY KEY,
            policy_id        TEXT NOT NULL,
            policy_name      TEXT NOT NULL,
            incident_id      TEXT NOT NULL,
            incident_title   TEXT NOT NULL,
            incident_severity TEXT NOT NULL DEFAULT '',
            breach_type      TEXT NOT NULL,
            breached_at      TEXT NOT NULL,
            notified         INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT NOT NULL,
            UNIQUE (incident_id, breach_type)
        );

        CREATE INDEX IF NOT EXISTS idx_sb_incident
            ON sla_breaches (incident_id, breach_type);
        CREATE INDEX IF NOT EXISTS idx_sb_created
            ON sla_breaches (created_at DESC);
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


# ── Breach detector ───────────────────────────────────────────────────────────

def _get_incident_db_path() -> str:
    try:
        from backend.api import incidents as inc
        return inc._DB_PATH
    except Exception:
        return str(Path(DATA_DIR) / "incidents.db")


def _fetch_open_incidents() -> list[dict]:
    inc_db = _get_incident_db_path()
    try:
        con = sqlite3.connect(inc_db, timeout=5)
        rows = con.execute(
            "SELECT id, title, severity, status, created_at "
            "FROM incidents WHERE status IN ('open','acknowledged')"
        ).fetchall()
        con.close()
        return [
            {"id": r[0], "title": r[1], "severity": r[2],
             "status": r[3], "created_at": r[4]}
            for r in rows
        ]
    except Exception as exc:
        logger.debug("SLA: could not fetch incidents: %s", exc)
        return []


def _insert_breach(policy: dict, incident: dict, breach_type: str) -> bool:
    """Returns True if a new breach was inserted (not a duplicate)."""
    breach_id = str(uuid.uuid4())
    now = _now()
    try:
        con = _conn()
        cur = con.execute(
            f"INSERT OR IGNORE INTO sla_breaches ({','.join(_BREACH_COLS)}) "
            f"VALUES ({','.join(['?']*len(_BREACH_COLS))})",
            (
                breach_id, policy["id"], policy["name"],
                incident["id"], incident["title"], incident["severity"],
                breach_type, now, 0, now,
            ),
        )
        inserted = cur.rowcount > 0
        con.commit()
        con.close()
        return inserted
    except Exception as exc:
        logger.warning("SLA: breach insert failed: %s", exc)
        return False


async def _emit_breach_event(policy: dict, incident: dict, breach_type: str) -> None:
    try:
        from backend.api.event_bus import get_event_bus
        await get_event_bus().publish({
            "type":       "sla.breach",
            "severity":   "high",
            "source":     "sla_checker",
            "id":         str(uuid.uuid4()),
            "payload": {
                "policy_id":        policy["id"],
                "policy_name":      policy["name"],
                "incident_id":      incident["id"],
                "incident_title":   incident["title"],
                "incident_severity": incident["severity"],
                "breach_type":      breach_type,
            },
            "created_at": _now(),
        })
    except Exception as exc:
        logger.debug("SLA: event emission failed: %s", exc)


def _add_incident_timeline(incident_id: str, breach_type: str, policy_name: str) -> None:
    try:
        from backend.api.incidents import _add_timeline
        note = (
            f"SLA breach: {breach_type} time limit exceeded "
            f"(policy: {policy_name})"
        )
        _add_timeline(incident_id, actor="sla_checker",
                      action="sla_breach", note=note)
    except Exception as exc:
        logger.debug("SLA: timeline entry failed: %s", exc)


async def _check_sla() -> None:
    try:
        con = _conn()
        rows = con.execute(
            f"SELECT {','.join(_POLICY_COLS)} FROM sla_policies WHERE enabled=1"
        ).fetchall()
        con.close()
    except Exception as exc:
        logger.debug("SLA: policy fetch failed: %s", exc)
        return

    policies = [dict(zip(_POLICY_COLS, r)) for r in rows]
    if not policies:
        return

    incidents = _fetch_open_incidents()
    if not incidents:
        return

    for incident in incidents:
        elapsed = _minutes_elapsed(incident["created_at"])
        for policy in policies:
            sev_filter = policy["severity"]
            if sev_filter and sev_filter != incident["severity"]:
                continue

            if incident["status"] == "open":
                if elapsed > policy["response_minutes"]:
                    if _insert_breach(policy, incident, "response"):
                        await _emit_breach_event(policy, incident, "response")
                        _add_incident_timeline(incident["id"], "response", policy["name"])

            if elapsed > policy["resolve_minutes"]:
                if _insert_breach(policy, incident, "resolve"):
                    await _emit_breach_event(policy, incident, "resolve")
                    _add_incident_timeline(incident["id"], "resolve", policy["name"])


# ── Background checker ────────────────────────────────────────────────────────

class SlaChecker:
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
                await _check_sla()
            except Exception as exc:
                logger.warning("SLA checker error: %s", exc)
            await asyncio.sleep(self.INTERVAL_S)


async def ensure_sla_running() -> None:
    global _running, _checker
    if _running:
        return
    _init_db()
    _running = True
    _checker = SlaChecker()
    _checker.start()
    logger.info("SLA checker started")


def get_checker() -> Optional[SlaChecker]:
    return _checker


# ── Pydantic schemas ──────────────────────────────────────────────────────────

_VALID_SEVERITIES = {"", "info", "low", "medium", "high", "critical"}


class PolicyCreate(BaseModel):
    name:             str
    severity:         str  = ""
    response_minutes: int  = 60
    resolve_minutes:  int  = 240
    enabled:          bool = True


class PolicyPatch(BaseModel):
    name:             Optional[str]  = None
    severity:         Optional[str]  = None
    response_minutes: Optional[int]  = None
    resolve_minutes:  Optional[int]  = None
    enabled:          Optional[bool] = None


# ── Sub-routes before /{policy_id} ────────────────────────────────────────────

@router.get("/policies/stats", summary="SLA policy statistics")
async def policy_stats(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        total   = con.execute("SELECT COUNT(*) FROM sla_policies").fetchone()[0]
        enabled = con.execute("SELECT COUNT(*) FROM sla_policies WHERE enabled=1").fetchone()[0]
        breaches_today = con.execute(
            "SELECT COUNT(*) FROM sla_breaches WHERE date(created_at) = date('now')"
        ).fetchone()[0]
        open_breaches = con.execute(
            "SELECT COUNT(*) FROM sla_breaches WHERE notified=0"
        ).fetchone()[0]
        by_type = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT breach_type, COUNT(*) FROM sla_breaches GROUP BY breach_type"
            ).fetchall()
        }
        con.close()
        return {
            "total_policies": total,
            "enabled_policies": enabled,
            "breaches_today": breaches_today,
            "open_breaches": open_breaches,
            "breaches_by_type": by_type,
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/status", summary="Current SLA compliance status")
async def sla_status(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        total_breaches = con.execute("SELECT COUNT(*) FROM sla_breaches").fetchone()[0]
        response_breaches = con.execute(
            "SELECT COUNT(*) FROM sla_breaches WHERE breach_type='response'"
        ).fetchone()[0]
        resolve_breaches = con.execute(
            "SELECT COUNT(*) FROM sla_breaches WHERE breach_type='resolve'"
        ).fetchone()[0]
        recent = con.execute(
            f"SELECT {','.join(_BREACH_COLS)} FROM sla_breaches "
            "ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        con.close()
        return {
            "total_breaches":    total_breaches,
            "response_breaches": response_breaches,
            "resolve_breaches":  resolve_breaches,
            "recent_breaches":   [dict(zip(_BREACH_COLS, r)) for r in recent],
            "checker_running":   _checker is not None and (
                _checker._task is not None and not _checker._task.done()
            ),
        }
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/breaches", summary="List SLA breaches")
async def list_breaches(
    breach_type: Optional[str] = Query(None),
    severity:    Optional[str] = Query(None),
    limit:       int = Query(100, ge=1, le=1000),
    offset:      int = Query(0,   ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if breach_type:
        where.append("breach_type = ?"); params.append(breach_type)
    if severity:
        where.append("incident_severity = ?"); params.append(severity)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM sla_breaches {clause}", params
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_BREACH_COLS)} FROM sla_breaches {clause} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "breaches": [dict(zip(_BREACH_COLS, r)) for r in rows],
        "total":    total,
        "limit":    limit,
        "offset":   offset,
    }


# ── Policy CRUD ───────────────────────────────────────────────────────────────

@router.get("/policies", summary="List SLA policies")
async def list_policies(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        rows = con.execute(
            f"SELECT {','.join(_POLICY_COLS)} FROM sla_policies ORDER BY created_at DESC"
        ).fetchall()
        con.close()
    except Exception:
        return {"policies": []}
    return {"policies": [dict(zip(_POLICY_COLS, r)) for r in rows]}


@router.post("/policies", status_code=201, summary="Create SLA policy")
async def create_policy(body: PolicyCreate, _auth=Depends(require_local_auth)):
    if body.severity not in _VALID_SEVERITIES:
        raise HTTPException(400, f"severity must be one of: {', '.join(sorted(_VALID_SEVERITIES)) or 'empty'}")
    if body.response_minutes < 1 or body.response_minutes > 525_600:
        raise HTTPException(400, "response_minutes must be 1–525600")
    if body.resolve_minutes < 1 or body.resolve_minutes > 525_600:
        raise HTTPException(400, "resolve_minutes must be 1–525600")
    if body.resolve_minutes <= body.response_minutes:
        raise HTTPException(400, "resolve_minutes must exceed response_minutes")
    pol_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO sla_policies ({','.join(_POLICY_COLS)}) "
            f"VALUES ({','.join(['?']*len(_POLICY_COLS))})",
            (pol_id, body.name, body.severity, body.response_minutes,
             body.resolve_minutes, 1 if body.enabled else 0, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": pol_id, "name": body.name}


@router.get("/policies/{policy_id}", summary="Get SLA policy")
async def get_policy(policy_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_POLICY_COLS)} FROM sla_policies WHERE id=?", (policy_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not row:
        raise HTTPException(404, "Policy not found")
    pol = dict(zip(_POLICY_COLS, row))
    try:
        con = _conn()
        breaches = con.execute(
            f"SELECT {','.join(_BREACH_COLS)} FROM sla_breaches "
            "WHERE policy_id=? ORDER BY created_at DESC LIMIT 20",
            (policy_id,),
        ).fetchall()
        con.close()
        pol["recent_breaches"] = [dict(zip(_BREACH_COLS, r)) for r in breaches]
    except Exception:
        pol["recent_breaches"] = []
    return pol


@router.patch("/policies/{policy_id}", summary="Update SLA policy")
async def patch_policy(
    policy_id: str, body: PolicyPatch, _auth=Depends(require_local_auth)
):
    updates, params = [], []
    if body.name is not None:
        updates.append("name = ?"); params.append(body.name)
    if body.severity is not None:
        if body.severity not in _VALID_SEVERITIES:
            raise HTTPException(400, "invalid severity")
        updates.append("severity = ?"); params.append(body.severity)
    if body.response_minutes is not None:
        if not (1 <= body.response_minutes <= 525_600):
            raise HTTPException(400, "response_minutes out of range")
        updates.append("response_minutes = ?"); params.append(body.response_minutes)
    if body.resolve_minutes is not None:
        if not (1 <= body.resolve_minutes <= 525_600):
            raise HTTPException(400, "resolve_minutes out of range")
        updates.append("resolve_minutes = ?"); params.append(body.resolve_minutes)
    if body.enabled is not None:
        updates.append("enabled = ?"); params.append(1 if body.enabled else 0)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at = ?"); params.append(_now())
    params.append(policy_id)
    try:
        con = _conn()
        con.execute(f"UPDATE sla_policies SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "Policy not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


@router.delete("/policies/{policy_id}", status_code=204, summary="Delete SLA policy")
async def delete_policy(policy_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM sla_breaches WHERE policy_id=?", (policy_id,))
        con.execute("DELETE FROM sla_policies WHERE id=?", (policy_id,))
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
