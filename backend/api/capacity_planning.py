"""
Capacity Planning
=================
Resource pool registry with point-in-time utilization snapshots,
4-state lifecycle and computed utilization percentages.

Tables:
  capacity_resources  — named resource pools
  capacity_snapshots  — append-only utilization records

State machine:
  active        → warning | critical | decommissioned
  warning       → active  | critical | decommissioned
  critical      → active  | warning  | decommissioned
  decommissioned → (terminal)

Resource types: cpu, memory, storage, network, seats, connections, custom

Snapshot: utilization_pct auto-computed as round(used/total*100, 2).
          After insert, resource status auto-escalates:
            ≥ 90% → critical, ≥ 75% → warning, < 75% → active
          (only if resource is not decommissioned)

Endpoints:
  GET    /capacity/resources
  POST   /capacity/resources                              (201)
  GET    /capacity/resources/stats
  GET    /capacity/resources/{resource_id}
  PATCH  /capacity/resources/{resource_id}
  DELETE /capacity/resources/{resource_id}               (204)
  POST   /capacity/resources/{resource_id}/transition
  GET    /capacity/resources/{resource_id}/snapshots
  POST   /capacity/resources/{resource_id}/snapshots     (201)
  GET    /capacity/snapshots                             (recent across all)
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
router = APIRouter(prefix="/capacity", tags=["capacity_planning"])

_DB_PATH = str(Path(DATA_DIR) / "capacity_planning.db")

_RES_COLS = [
    "id", "name", "type", "unit", "total_capacity", "allocated_capacity",
    "reserved_capacity", "environment", "owner", "team",
    "asset_id", "service_id", "status", "notes",
    "created_at", "updated_at",
]
_SNAP_COLS = [
    "id", "resource_id", "used", "total", "utilization_pct",
    "recorded_at", "notes",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "active":         {"warning", "critical", "decommissioned"},
    "warning":        {"active",  "critical", "decommissioned"},
    "critical":       {"active",  "warning",  "decommissioned"},
    "decommissioned": set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_TYPES = {
    "cpu", "memory", "storage", "network", "seats", "connections", "custom",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS capacity_resources (
            id                 TEXT PRIMARY KEY,
            name               TEXT NOT NULL,
            type               TEXT NOT NULL DEFAULT 'custom',
            unit               TEXT NOT NULL DEFAULT '',
            total_capacity     REAL NOT NULL DEFAULT 0,
            allocated_capacity REAL NOT NULL DEFAULT 0,
            reserved_capacity  REAL NOT NULL DEFAULT 0,
            environment        TEXT NOT NULL DEFAULT '',
            owner              TEXT NOT NULL DEFAULT '',
            team               TEXT NOT NULL DEFAULT '',
            asset_id           TEXT,
            service_id         TEXT,
            status             TEXT NOT NULL DEFAULT 'active',
            notes              TEXT NOT NULL DEFAULT '',
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS capacity_snapshots (
            id              TEXT PRIMARY KEY,
            resource_id     TEXT NOT NULL,
            used            REAL NOT NULL,
            total           REAL NOT NULL,
            utilization_pct REAL NOT NULL,
            recorded_at     TEXT NOT NULL,
            notes           TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_cap_status ON capacity_resources (status);
        CREATE INDEX IF NOT EXISTS idx_cap_type   ON capacity_resources (type);
        CREATE INDEX IF NOT EXISTS idx_cap_env    ON capacity_resources (environment);
        CREATE INDEX IF NOT EXISTS idx_snap_res   ON capacity_snapshots (resource_id, recorded_at DESC);
        CREATE INDEX IF NOT EXISTS idx_snap_time  ON capacity_snapshots (recorded_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_res_or_404(con: sqlite3.Connection, resource_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_RES_COLS)} FROM capacity_resources WHERE id=?",
        (resource_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Resource not found")
    return row


def _auto_status(pct: float) -> str:
    if pct >= 90:
        return "critical"
    if pct >= 75:
        return "warning"
    return "active"


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ResourceCreate(BaseModel):
    name:               str
    type:               str   = "custom"
    unit:               str   = ""
    total_capacity:     float = 0.0
    allocated_capacity: float = 0.0
    reserved_capacity:  float = 0.0
    environment:        str   = ""
    owner:              str   = ""
    team:               str   = ""
    asset_id:           Optional[str] = None
    service_id:         Optional[str] = None
    notes:              str   = ""

    @field_validator("total_capacity", "allocated_capacity", "reserved_capacity")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Capacity values must be non-negative")
        return v


class ResourcePatch(BaseModel):
    name:               Optional[str]   = None
    type:               Optional[str]   = None
    unit:               Optional[str]   = None
    total_capacity:     Optional[float] = None
    allocated_capacity: Optional[float] = None
    reserved_capacity:  Optional[float] = None
    environment:        Optional[str]   = None
    owner:              Optional[str]   = None
    team:               Optional[str]   = None
    asset_id:           Optional[str]   = None
    service_id:         Optional[str]   = None
    notes:              Optional[str]   = None


class TransitionBody(BaseModel):
    status: str
    notes:  str = ""


class SnapshotCreate(BaseModel):
    used:  float
    total: float
    notes: str = ""

    @field_validator("used", "total")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Snapshot values must be non-negative")
        return v


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("/resources", summary="List capacity resources")
async def list_resources(
    q:           Optional[str] = Query(None),
    type:        Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    environment: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(name LIKE ? OR notes LIKE ? OR owner LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct]
    if type:
        where.append("type = ?"); params.append(type)
    if status:
        where.append("status = ?"); params.append(status)
    if environment:
        where.append("environment = ?"); params.append(environment)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM capacity_resources {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_RES_COLS)} FROM capacity_resources {clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "resources": [dict(zip(_RES_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("/resources", status_code=201, summary="Create capacity resource")
async def create_resource(body: ResourceCreate, _auth=Depends(require_local_auth)):
    if body.type not in _VALID_TYPES:
        raise HTTPException(400, f"Invalid type '{body.type}'. Valid: {sorted(_VALID_TYPES)}")
    res_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO capacity_resources ({','.join(_RES_COLS)}) "
            f"VALUES ({','.join(['?']*len(_RES_COLS))})",
            (res_id, body.name, body.type, body.unit,
             body.total_capacity, body.allocated_capacity, body.reserved_capacity,
             body.environment, body.owner, body.team,
             body.asset_id, body.service_id, "active", body.notes, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": res_id, "name": body.name, "status": "active"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/resources/stats", summary="Capacity planning statistics")
async def capacity_stats(_auth=Depends(require_local_auth)):
    try:
        con     = _conn()
        total   = con.execute("SELECT COUNT(*) FROM capacity_resources").fetchone()[0]
        critical = con.execute(
            "SELECT COUNT(*) FROM capacity_resources WHERE status='critical'"
        ).fetchone()[0]
        warning  = con.execute(
            "SELECT COUNT(*) FROM capacity_resources WHERE status='warning'"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM capacity_resources GROUP BY status"
        ).fetchall()
        by_type  = con.execute(
            "SELECT type, COUNT(*) FROM capacity_resources "
            "GROUP BY type ORDER BY COUNT(*) DESC"
        ).fetchall()
        recent_snaps = con.execute(
            "SELECT COUNT(*) FROM capacity_snapshots "
            "WHERE recorded_at >= datetime('now','-24 hours')"
        ).fetchone()[0]
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":        total,
        "critical":     critical,
        "warning":      warning,
        "recent_snapshots": recent_snaps,
        "by_status":    [{"status": s, "count": c} for s, c in by_status],
        "by_type":      [{"type": t, "count": c} for t, c in by_type],
    }


# ── Single resource ───────────────────────────────────────────────────────────

@router.get("/resources/{resource_id}", summary="Get capacity resource")
async def get_resource(resource_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_res_or_404(con, resource_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_RES_COLS, row))


@router.patch("/resources/{resource_id}", summary="Update capacity resource")
async def patch_resource(
    resource_id: str, body: ResourcePatch, _auth=Depends(require_local_auth)
):
    if body.type is not None and body.type not in _VALID_TYPES:
        raise HTTPException(400, f"Invalid type '{body.type}'. Valid: {sorted(_VALID_TYPES)}")
    for field in ("total_capacity", "allocated_capacity", "reserved_capacity"):
        val = getattr(body, field)
        if val is not None and val < 0:
            raise HTTPException(400, f"'{field}' must be non-negative")
    try:
        con = _conn()
        _get_res_or_404(con, resource_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "type", "unit", "total_capacity", "allocated_capacity",
                      "reserved_capacity", "environment", "owner", "team",
                      "asset_id", "service_id", "notes"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(resource_id)
        con.execute(f"UPDATE capacity_resources SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_RES_COLS)} FROM capacity_resources WHERE id=?",
            (resource_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_RES_COLS, row))


@router.delete("/resources/{resource_id}", status_code=204,
               summary="Delete capacity resource")
async def delete_resource(resource_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_res_or_404(con, resource_id)
        con.execute("DELETE FROM capacity_snapshots WHERE resource_id=?", (resource_id,))
        con.execute("DELETE FROM capacity_resources WHERE id=?", (resource_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/resources/{resource_id}/transition",
             summary="Transition resource status")
async def transition_resource(
    resource_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_res_or_404(con, resource_id)
        d   = dict(zip(_RES_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        now = _now()
        con.execute(
            "UPDATE capacity_resources SET status=?, updated_at=? WHERE id=?",
            (body.status, now, resource_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Snapshots ─────────────────────────────────────────────────────────────────

@router.get("/resources/{resource_id}/snapshots",
            summary="List snapshots for a resource")
async def list_snapshots(
    resource_id: str,
    limit:  int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_res_or_404(con, resource_id)
        total = con.execute(
            "SELECT COUNT(*) FROM capacity_snapshots WHERE resource_id=?",
            (resource_id,),
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_SNAP_COLS)} FROM capacity_snapshots "
            "WHERE resource_id=? ORDER BY recorded_at DESC LIMIT ? OFFSET ?",
            (resource_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"snapshots": [dict(zip(_SNAP_COLS, r)) for r in rows], "total": total}


@router.post("/resources/{resource_id}/snapshots", status_code=201,
             summary="Record utilization snapshot")
async def add_snapshot(
    resource_id: str, body: SnapshotCreate, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        row = _get_res_or_404(con, resource_id)
        d   = dict(zip(_RES_COLS, row))
        snap_id = str(uuid.uuid4())
        now     = _now()
        pct = round(body.used / body.total * 100, 2) if body.total > 0 else 0.0
        con.execute(
            f"INSERT INTO capacity_snapshots ({','.join(_SNAP_COLS)}) "
            f"VALUES ({','.join(['?']*len(_SNAP_COLS))})",
            (snap_id, resource_id, body.used, body.total, pct, now, body.notes),
        )
        if d["status"] != "decommissioned":
            new_status = _auto_status(pct)
            con.execute(
                "UPDATE capacity_resources SET status=?, updated_at=? WHERE id=?",
                (new_status, now, resource_id),
            )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": snap_id, "utilization_pct": pct, "ok": True}


# ── Global recent snapshots ───────────────────────────────────────────────────

@router.get("/snapshots", summary="Recent snapshots across all resources")
async def recent_snapshots(
    limit: int = Query(50, ge=1, le=500),
    _auth=Depends(require_local_auth),
):
    try:
        con  = _conn()
        rows = con.execute(
            f"SELECT {','.join(_SNAP_COLS)} FROM capacity_snapshots "
            "ORDER BY recorded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"snapshots": [dict(zip(_SNAP_COLS, r)) for r in rows]}
