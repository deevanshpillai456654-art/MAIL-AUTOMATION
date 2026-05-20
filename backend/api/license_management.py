"""
License Management
==================
Software license registry with seat assignment tracking, renewal history
and 5-state lifecycle.

Tables:
  licenses    — license records (product, vendor, seats, expiry, cost)
  assignments — per-user/service seat assignments (auto-adjusts seats_used)
  renewals    — renewal history with cost and date

State machine:
  draft      → active | cancelled
  active     → expired | suspended | terminated
  expired    → active
  suspended  → active | terminated
  terminated → (terminal)
  cancelled  → (terminal)

seats_used is auto-incremented on assignment add and decremented on delete.
Computed at query time:
  seats_available = seats_total - seats_used
  utilization_pct = seats_used / seats_total * 100

License types: perpetual, subscription, trial, open_source, volume, enterprise

Endpoints:
  GET    /licenses
  POST   /licenses                                           (201)
  GET    /licenses/stats
  GET    /licenses/expiring                                  (?days=30)
  GET    /licenses/{license_id}
  PATCH  /licenses/{license_id}
  DELETE /licenses/{license_id}                             (204)
  POST   /licenses/{license_id}/transition
  GET    /licenses/{license_id}/assignments
  POST   /licenses/{license_id}/assignments                 (201)
  DELETE /licenses/{license_id}/assignments/{assignment_id} (204)
  GET    /licenses/{license_id}/renewals
  POST   /licenses/{license_id}/renewals                    (201)
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
router = APIRouter(tags=["license_management"])

_DB_PATH = str(Path(DATA_DIR) / "license_management.db")

_LIC_COLS = [
    "id", "name", "product", "vendor", "type", "status",
    "seats_total", "seats_used", "cost", "currency",
    "purchase_date", "expiry_date", "owner", "team", "notes",
    "created_at", "updated_at",
]
_ASN_COLS = [
    "id", "license_id", "user", "email", "assigned_date", "notes", "created_at",
]
_REN_COLS = [
    "id", "license_id", "amount", "renewal_date", "notes", "author", "created_at",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":      {"active", "cancelled"},
    "active":     {"expired", "suspended", "terminated"},
    "expired":    {"active"},
    "suspended":  {"active", "terminated"},
    "terminated": set(),
    "cancelled":  set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_TYPES = {
    "perpetual", "subscription", "trial", "open_source", "volume", "enterprise",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS licenses (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            product       TEXT NOT NULL DEFAULT '',
            vendor        TEXT NOT NULL DEFAULT '',
            type          TEXT NOT NULL DEFAULT 'subscription',
            status        TEXT NOT NULL DEFAULT 'draft',
            seats_total   INTEGER NOT NULL DEFAULT 0,
            seats_used    INTEGER NOT NULL DEFAULT 0,
            cost          REAL NOT NULL DEFAULT 0.0,
            currency      TEXT NOT NULL DEFAULT 'USD',
            purchase_date TEXT NOT NULL DEFAULT '',
            expiry_date   TEXT NOT NULL DEFAULT '',
            owner         TEXT NOT NULL DEFAULT '',
            team          TEXT NOT NULL DEFAULT '',
            notes         TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id            TEXT PRIMARY KEY,
            license_id    TEXT NOT NULL,
            user          TEXT NOT NULL DEFAULT '',
            email         TEXT NOT NULL DEFAULT '',
            assigned_date TEXT NOT NULL DEFAULT '',
            notes         TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS renewals (
            id           TEXT PRIMARY KEY,
            license_id   TEXT NOT NULL,
            amount       REAL NOT NULL DEFAULT 0.0,
            renewal_date TEXT NOT NULL DEFAULT '',
            notes        TEXT NOT NULL DEFAULT '',
            author       TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_lic_status  ON licenses (status);
        CREATE INDEX IF NOT EXISTS idx_lic_type    ON licenses (type);
        CREATE INDEX IF NOT EXISTS idx_lic_expiry  ON licenses (expiry_date);
        CREATE INDEX IF NOT EXISTS idx_asn_license ON assignments (license_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ren_license ON renewals (license_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_lic_or_404(con: sqlite3.Connection, license_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_LIC_COLS)} FROM licenses WHERE id=?",
        (license_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "License not found")
    return row


def _enrich(d: dict) -> dict:
    total = d.get("seats_total") or 0
    used  = d.get("seats_used")  or 0
    avail = total - used
    pct   = round(used / total * 100, 2) if total > 0 else 0.0
    return {**d, "seats_available": avail, "utilization_pct": pct}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class LicenseCreate(BaseModel):
    name:          str
    product:       str   = ""
    vendor:        str   = ""
    type:          str   = "subscription"
    seats_total:   int   = 0
    cost:          float = 0.0
    currency:      str   = "USD"
    purchase_date: str   = ""
    expiry_date:   str   = ""
    owner:         str   = ""
    team:          str   = ""
    notes:         str   = ""

    @field_validator("seats_total")
    @classmethod
    def non_negative_seats(cls, v: int) -> int:
        if v < 0:
            raise ValueError("seats_total must be non-negative")
        return v

    @field_validator("cost")
    @classmethod
    def non_negative_cost(cls, v: float) -> float:
        if v < 0:
            raise ValueError("cost must be non-negative")
        return v


class LicensePatch(BaseModel):
    name:          Optional[str]   = None
    product:       Optional[str]   = None
    vendor:        Optional[str]   = None
    type:          Optional[str]   = None
    seats_total:   Optional[int]   = None
    cost:          Optional[float] = None
    currency:      Optional[str]   = None
    purchase_date: Optional[str]   = None
    expiry_date:   Optional[str]   = None
    owner:         Optional[str]   = None
    team:          Optional[str]   = None
    notes:         Optional[str]   = None


class TransitionBody(BaseModel):
    status: str
    notes:  str = ""


class AssignmentCreate(BaseModel):
    user:          str = ""
    email:         str = ""
    assigned_date: str = ""
    notes:         str = ""


class RenewalCreate(BaseModel):
    amount:       float = 0.0
    renewal_date: str   = ""
    notes:        str   = ""
    author:       str   = ""

    @field_validator("amount")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("amount must be non-negative")
        return v


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("/licenses", summary="List licenses")
async def list_licenses(
    q:      Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    type:   Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append(
            "(name LIKE ? OR product LIKE ? OR vendor LIKE ? OR owner LIKE ? OR team LIKE ?)"
        )
        pct = f"%{q}%"
        params += [pct, pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if type:
        where.append("type = ?"); params.append(type)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM licenses {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_LIC_COLS)} FROM licenses {clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "licenses": [_enrich(dict(zip(_LIC_COLS, r))) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("/licenses", status_code=201, summary="Create license")
async def create_license(body: LicenseCreate, _auth=Depends(require_local_auth)):
    if body.type not in _VALID_TYPES:
        raise HTTPException(
            400, f"Invalid type '{body.type}'. Valid: {sorted(_VALID_TYPES)}"
        )
    lic_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO licenses ({','.join(_LIC_COLS)}) "
            f"VALUES ({','.join(['?']*len(_LIC_COLS))})",
            (lic_id, body.name, body.product, body.vendor, body.type, "draft",
             body.seats_total, 0, body.cost, body.currency,
             body.purchase_date, body.expiry_date, body.owner, body.team,
             body.notes, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": lic_id, "name": body.name, "status": "draft"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/licenses/stats", summary="License statistics")
async def license_stats(_auth=Depends(require_local_auth)):
    try:
        con        = _conn()
        total      = con.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
        active     = con.execute(
            "SELECT COUNT(*) FROM licenses WHERE status='active'"
        ).fetchone()[0]
        expiring   = con.execute(
            "SELECT COUNT(*) FROM licenses "
            "WHERE expiry_date != '' AND expiry_date <= date('now', '+30 days') "
            "AND status NOT IN ('terminated','cancelled')"
        ).fetchone()[0]
        total_cost = con.execute(
            "SELECT COALESCE(SUM(cost), 0) FROM licenses WHERE status='active'"
        ).fetchone()[0]
        total_seats = con.execute(
            "SELECT COALESCE(SUM(seats_total), 0) FROM licenses WHERE status='active'"
        ).fetchone()[0]
        used_seats  = con.execute(
            "SELECT COALESCE(SUM(seats_used), 0) FROM licenses WHERE status='active'"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM licenses GROUP BY status"
        ).fetchall()
        by_type   = con.execute(
            "SELECT type, COUNT(*) FROM licenses GROUP BY type ORDER BY COUNT(*) DESC"
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":        total,
        "active":       active,
        "expiring_30":  expiring,
        "total_cost":   round(total_cost, 2),
        "total_seats":  total_seats,
        "used_seats":   used_seats,
        "by_status":    [{"status": s, "count": c} for s, c in by_status],
        "by_type":      [{"type": t, "count": c} for t, c in by_type],
    }


# ── Expiring ──────────────────────────────────────────────────────────────────

@router.get("/licenses/expiring", summary="Licenses expiring within N days")
async def expiring_licenses(
    days: int = Query(30, ge=1, le=365),
    _auth=Depends(require_local_auth),
):
    interval = f"+{days} days"
    try:
        con  = _conn()
        rows = con.execute(
            f"SELECT {','.join(_LIC_COLS)} FROM licenses "
            "WHERE expiry_date != '' "
            "  AND expiry_date <= date('now', ?) "
            "  AND status NOT IN ('terminated','cancelled') "
            "ORDER BY expiry_date ASC",
            (interval,),
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"licenses": [_enrich(dict(zip(_LIC_COLS, r))) for r in rows]}


# ── Single license ────────────────────────────────────────────────────────────

@router.get("/licenses/{license_id}", summary="Get license with seat summary")
async def get_license(license_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_lic_or_404(con, license_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_LIC_COLS, row)))


@router.patch("/licenses/{license_id}", summary="Update license")
async def patch_license(
    license_id: str, body: LicensePatch, _auth=Depends(require_local_auth)
):
    if body.type is not None and body.type not in _VALID_TYPES:
        raise HTTPException(400, f"Invalid type. Valid: {sorted(_VALID_TYPES)}")
    if body.seats_total is not None and body.seats_total < 0:
        raise HTTPException(400, "seats_total must be non-negative")
    if body.cost is not None and body.cost < 0:
        raise HTTPException(400, "cost must be non-negative")
    try:
        con = _conn()
        _get_lic_or_404(con, license_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "product", "vendor", "type", "seats_total",
                      "cost", "currency", "purchase_date", "expiry_date",
                      "owner", "team", "notes"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(license_id)
        con.execute(f"UPDATE licenses SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_LIC_COLS)} FROM licenses WHERE id=?",
            (license_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_LIC_COLS, row)))


@router.delete("/licenses/{license_id}", status_code=204, summary="Delete license")
async def delete_license(license_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_lic_or_404(con, license_id)
        con.execute("DELETE FROM assignments WHERE license_id=?", (license_id,))
        con.execute("DELETE FROM renewals    WHERE license_id=?", (license_id,))
        con.execute("DELETE FROM licenses    WHERE id=?",         (license_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/licenses/{license_id}/transition", summary="Transition license status")
async def transition_license(
    license_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_lic_or_404(con, license_id)
        d   = dict(zip(_LIC_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        now = _now()
        con.execute(
            "UPDATE licenses SET status=?, updated_at=? WHERE id=?",
            (body.status, now, license_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Assignments ───────────────────────────────────────────────────────────────

@router.get("/licenses/{license_id}/assignments", summary="List seat assignments")
async def list_assignments(license_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_lic_or_404(con, license_id)
        rows = con.execute(
            f"SELECT {','.join(_ASN_COLS)} FROM assignments "
            "WHERE license_id=? ORDER BY created_at DESC",
            (license_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"assignments": [dict(zip(_ASN_COLS, r)) for r in rows]}


@router.post("/licenses/{license_id}/assignments", status_code=201,
             summary="Add seat assignment")
async def add_assignment(
    license_id: str, body: AssignmentCreate, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_lic_or_404(con, license_id)
        asn_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO assignments ({','.join(_ASN_COLS)}) "
            f"VALUES ({','.join(['?']*len(_ASN_COLS))})",
            (asn_id, license_id, body.user, body.email,
             body.assigned_date, body.notes, now),
        )
        con.execute(
            "UPDATE licenses SET seats_used = seats_used + 1, updated_at=? WHERE id=?",
            (now, license_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": asn_id, "ok": True}


@router.delete("/licenses/{license_id}/assignments/{assignment_id}", status_code=204,
               summary="Remove seat assignment")
async def delete_assignment(
    license_id: str, assignment_id: str, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_lic_or_404(con, license_id)
        row = con.execute(
            "SELECT id FROM assignments WHERE id=? AND license_id=?",
            (assignment_id, license_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Assignment not found")
        con.execute("DELETE FROM assignments WHERE id=?", (assignment_id,))
        con.execute(
            "UPDATE licenses SET seats_used = MAX(0, seats_used - 1), updated_at=? WHERE id=?",
            (_now(), license_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Renewals ──────────────────────────────────────────────────────────────────

@router.get("/licenses/{license_id}/renewals", summary="List renewal history")
async def list_renewals(license_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_lic_or_404(con, license_id)
        rows = con.execute(
            f"SELECT {','.join(_REN_COLS)} FROM renewals "
            "WHERE license_id=? ORDER BY created_at DESC",
            (license_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"renewals": [dict(zip(_REN_COLS, r)) for r in rows]}


@router.post("/licenses/{license_id}/renewals", status_code=201,
             summary="Record renewal")
async def add_renewal(
    license_id: str, body: RenewalCreate, _auth=Depends(require_local_auth)
):
    try:
        con    = _conn()
        _get_lic_or_404(con, license_id)
        ren_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO renewals ({','.join(_REN_COLS)}) "
            f"VALUES ({','.join(['?']*len(_REN_COLS))})",
            (ren_id, license_id, body.amount, body.renewal_date,
             body.notes, body.author, now),
        )
        con.execute(
            "UPDATE licenses SET updated_at=? WHERE id=?", (now, license_id)
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": ren_id, "ok": True}
