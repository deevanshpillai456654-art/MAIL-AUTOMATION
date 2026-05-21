"""
SLO Management
==============
Service Level Objective registry with error budget computation, breach
detection from measurements and 5-state lifecycle.

Tables:
  slos             — SLO definitions (service, target_pct, time_window)
  slo_measurements — periodic actual_pct recordings

Computed at query time (from the latest measurement for each SLO):
  error_budget_pct          = 100 - target_pct
  latest_actual_pct         = actual_pct of most-recent measurement (null if none)
  is_breaching              = latest_actual_pct < target_pct
  error_budget_consumed_pct = max(0, (target - actual) / error_budget * 100)

State machine:
  draft      → active | cancelled
  active     → paused | deprecated
  paused     → active | deprecated
  deprecated → (terminal)
  cancelled  → (terminal)

Time windows: rolling_7d, rolling_30d, rolling_90d, calendar_month

Endpoints:
  GET    /slos
  POST   /slos                              (201)
  GET    /slos/stats
  GET    /slos/{slo_id}
  PATCH  /slos/{slo_id}
  DELETE /slos/{slo_id}                    (204)
  POST   /slos/{slo_id}/transition
  GET    /slos/{slo_id}/measurements
  POST   /slos/{slo_id}/measurements       (201)
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(tags=["slo_management"])

_DB_PATH = str(Path(DATA_DIR) / "slo_management.db")

_SLO_COLS = [
    "id", "name", "service", "description", "target_pct",
    "time_window", "status", "owner", "team", "tags",
    "created_at", "updated_at",
]
_MEAS_COLS = [
    "id", "slo_id", "actual_pct", "good_events", "total_events",
    "period_start", "period_end", "notes", "recorded_at",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":      {"active", "cancelled"},
    "active":     {"paused", "deprecated"},
    "paused":     {"active", "deprecated"},
    "deprecated": set(),
    "cancelled":  set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_TIME_WINDOWS = {"rolling_7d", "rolling_30d", "rolling_90d", "calendar_month"}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS slos (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            service     TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            target_pct  REAL NOT NULL DEFAULT 99.9,
            time_window TEXT NOT NULL DEFAULT 'rolling_30d',
            status      TEXT NOT NULL DEFAULT 'draft',
            owner       TEXT NOT NULL DEFAULT '',
            team        TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS slo_measurements (
            id           TEXT PRIMARY KEY,
            slo_id       TEXT NOT NULL,
            actual_pct   REAL NOT NULL,
            good_events  INTEGER NOT NULL DEFAULT 0,
            total_events INTEGER NOT NULL DEFAULT 0,
            period_start TEXT NOT NULL DEFAULT '',
            period_end   TEXT NOT NULL DEFAULT '',
            notes        TEXT NOT NULL DEFAULT '',
            recorded_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_slo_status  ON slos (status);
        CREATE INDEX IF NOT EXISTS idx_slo_service ON slos (service);
        CREATE INDEX IF NOT EXISTS idx_slo_owner   ON slos (owner);
        CREATE INDEX IF NOT EXISTS idx_slo_team    ON slos (team);
        CREATE INDEX IF NOT EXISTS idx_slo_window  ON slos (time_window);
        CREATE INDEX IF NOT EXISTS idx_meas_slo    ON slo_measurements (slo_id, recorded_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_slo_or_404(con: sqlite3.Connection, slo_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_SLO_COLS)} FROM slos WHERE id=?", (slo_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "SLO not found")
    return row


def _latest_actual(con: sqlite3.Connection, slo_id: str) -> Optional[float]:
    row = con.execute(
        "SELECT actual_pct FROM slo_measurements "
        "WHERE slo_id=? ORDER BY recorded_at DESC LIMIT 1",
        (slo_id,),
    ).fetchone()
    return row[0] if row else None


def _enrich(d: dict, actual: Optional[float]) -> dict:
    target       = d.get("target_pct") or 100.0
    error_budget = round(100.0 - target, 6)
    if actual is None:
        return {
            **d,
            "error_budget_pct": round(error_budget, 4),
            "latest_actual_pct": None,
            "is_breaching": None,
            "error_budget_consumed_pct": None,
        }
    is_breaching = actual < target
    if error_budget > 0:
        consumed = round(max(0.0, (target - actual) / error_budget * 100), 2)
    else:
        consumed = 100.0 if is_breaching else 0.0
    return {
        **d,
        "error_budget_pct": round(error_budget, 4),
        "latest_actual_pct": actual,
        "is_breaching": is_breaching,
        "error_budget_consumed_pct": consumed,
    }


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SLOCreate(BaseModel):
    name:        str
    service:     str   = ""
    description: str   = ""
    target_pct:  float = 99.9
    time_window: str   = "rolling_30d"
    owner:       str   = ""
    team:        str   = ""
    tags:        str   = ""

    @field_validator("target_pct")
    @classmethod
    def valid_pct(cls, v: float) -> float:
        if not (0 < v <= 100):
            raise ValueError("target_pct must be > 0 and <= 100")
        return v


class SLOPatch(BaseModel):
    name:        Optional[str]   = None
    service:     Optional[str]   = None
    description: Optional[str]   = None
    target_pct:  Optional[float] = None
    time_window: Optional[str]   = None
    owner:       Optional[str]   = None
    team:        Optional[str]   = None
    tags:        Optional[str]   = None

    @field_validator("target_pct")
    @classmethod
    def valid_pct(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 < v <= 100):
            raise ValueError("target_pct must be > 0 and <= 100")
        return v


class TransitionBody(BaseModel):
    status: str
    notes:  str = ""


class MeasurementCreate(BaseModel):
    actual_pct:   float
    good_events:  int = 0
    total_events: int = 0
    period_start: str = ""
    period_end:   str = ""
    notes:        str = ""

    @field_validator("actual_pct")
    @classmethod
    def valid_pct(cls, v: float) -> float:
        if not (0 <= v <= 100):
            raise ValueError("actual_pct must be between 0 and 100")
        return v


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("/slos", summary="List SLOs")
async def list_slos(
    q:           Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    time_window: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append(
            "(name LIKE ? OR service LIKE ? OR owner LIKE ? OR tags LIKE ?)"
        )
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if time_window:
        where.append("time_window = ?"); params.append(time_window)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM slos {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_SLO_COLS)} FROM slos {clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        result = []
        for r in rows:
            d      = dict(zip(_SLO_COLS, r))
            actual = _latest_actual(con, d["id"])
            result.append(_enrich(d, actual))
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"slos": result, "total": total, "limit": limit, "offset": offset}


@router.post("/slos", status_code=201, summary="Create SLO")
async def create_slo(body: SLOCreate, _auth=Depends(require_local_auth)):
    if body.time_window not in _VALID_TIME_WINDOWS:
        raise HTTPException(
            400, f"Invalid time_window '{body.time_window}'. Valid: {sorted(_VALID_TIME_WINDOWS)}"
        )
    slo_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO slos ({','.join(_SLO_COLS)}) "
            f"VALUES ({','.join(['?']*len(_SLO_COLS))})",
            (slo_id, body.name, body.service, body.description,
             body.target_pct, body.time_window, "draft",
             body.owner, body.team, body.tags, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "id": slo_id, "name": body.name, "status": "draft",
        "target_pct": body.target_pct,
        "error_budget_pct": round(100.0 - body.target_pct, 4),
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/slos/stats", summary="SLO statistics")
async def slo_stats(_auth=Depends(require_local_auth)):
    try:
        con       = _conn()
        total     = con.execute("SELECT COUNT(*) FROM slos").fetchone()[0]
        active    = con.execute(
            "SELECT COUNT(*) FROM slos WHERE status='active'"
        ).fetchone()[0]
        avg_target = con.execute(
            "SELECT AVG(target_pct) FROM slos WHERE status='active'"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM slos GROUP BY status"
        ).fetchall()
        by_window = con.execute(
            "SELECT time_window, COUNT(*) FROM slos "
            "GROUP BY time_window ORDER BY COUNT(*) DESC"
        ).fetchall()
        # Count active SLOs that are currently breaching (latest measurement < target)
        active_rows = con.execute(
            f"SELECT {','.join(_SLO_COLS)} FROM slos WHERE status='active' LIMIT 5000"
        ).fetchall()
        breaching = 0
        for row in active_rows:
            d      = dict(zip(_SLO_COLS, row))
            actual = _latest_actual(con, d["id"])
            if actual is not None and actual < d["target_pct"]:
                breaching += 1
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":      total,
        "active":     active,
        "breaching":  breaching,
        "avg_target": round(avg_target, 4) if avg_target else None,
        "by_status":  [{"status": s, "count": c} for s, c in by_status],
        "by_window":  [{"time_window": w, "count": c} for w, c in by_window],
    }


# ── Single SLO ────────────────────────────────────────────────────────────────

@router.get("/slos/{slo_id}", summary="Get SLO with error budget")
async def get_slo(slo_id: str, _auth=Depends(require_local_auth)):
    try:
        con    = _conn()
        row    = _get_slo_or_404(con, slo_id)
        d      = dict(zip(_SLO_COLS, row))
        actual = _latest_actual(con, slo_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(d, actual)


@router.patch("/slos/{slo_id}", summary="Update SLO")
async def patch_slo(
    slo_id: str, body: SLOPatch, _auth=Depends(require_local_auth)
):
    if body.time_window is not None and body.time_window not in _VALID_TIME_WINDOWS:
        raise HTTPException(400, f"Invalid time_window. Valid: {sorted(_VALID_TIME_WINDOWS)}")
    try:
        con = _conn()
        _get_slo_or_404(con, slo_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "service", "description", "target_pct",
                      "time_window", "owner", "team", "tags"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(slo_id)
        con.execute(f"UPDATE slos SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row    = con.execute(
            f"SELECT {','.join(_SLO_COLS)} FROM slos WHERE id=?", (slo_id,)
        ).fetchone()
        actual = _latest_actual(con, slo_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_SLO_COLS, row)), actual)


@router.delete("/slos/{slo_id}", status_code=204, summary="Delete SLO")
async def delete_slo(slo_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_slo_or_404(con, slo_id)
        con.execute("DELETE FROM slo_measurements WHERE slo_id=?", (slo_id,))
        con.execute("DELETE FROM slos             WHERE id=?",     (slo_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/slos/{slo_id}/transition", summary="Transition SLO status")
async def transition_slo(
    slo_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_slo_or_404(con, slo_id)
        d   = dict(zip(_SLO_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        con.execute(
            "UPDATE slos SET status=?, updated_at=? WHERE id=?",
            (body.status, _now(), slo_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Measurements ──────────────────────────────────────────────────────────────

@router.get("/slos/{slo_id}/measurements", summary="List SLO measurements")
async def list_measurements(
    slo_id: str,
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_slo_or_404(con, slo_id)
        total = con.execute(
            "SELECT COUNT(*) FROM slo_measurements WHERE slo_id=?", (slo_id,)
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_MEAS_COLS)} FROM slo_measurements "
            "WHERE slo_id=? ORDER BY recorded_at DESC LIMIT ? OFFSET ?",
            (slo_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "measurements": [dict(zip(_MEAS_COLS, r)) for r in rows],
        "total": total,
    }


@router.post("/slos/{slo_id}/measurements", status_code=201,
             summary="Record SLO measurement")
async def add_measurement(
    slo_id: str, body: MeasurementCreate, _auth=Depends(require_local_auth)
):
    try:
        con    = _conn()
        row    = _get_slo_or_404(con, slo_id)
        d      = dict(zip(_SLO_COLS, row))
        meas_id = str(uuid.uuid4())
        now     = _now()
        con.execute(
            f"INSERT INTO slo_measurements ({','.join(_MEAS_COLS)}) "
            f"VALUES ({','.join(['?']*len(_MEAS_COLS))})",
            (meas_id, slo_id, body.actual_pct, body.good_events,
             body.total_events, body.period_start, body.period_end,
             body.notes, now),
        )
        con.execute(
            "UPDATE slos SET updated_at=? WHERE id=?", (now, slo_id)
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    is_breaching = body.actual_pct < d["target_pct"]
    return {"id": meas_id, "is_breaching": is_breaching, "ok": True}
