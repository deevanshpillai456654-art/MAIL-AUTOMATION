"""
Vendor Management
=================
Third-party vendor registry with contract lifecycle tracking,
contact directory, periodic reviews and expiry alerting.

Tables:
  vendors          — vendor records
  vendor_contacts  — per-vendor contact directory
  vendor_reviews   — periodic review log (rating 1-5)

State machine:
  active       → under_review | suspended | terminated
  under_review → active       | suspended | terminated
  suspended    → active       | terminated
  terminated   → (terminal)

Vendor categories: software, hardware, cloud, consulting, support, other

Endpoints:
  GET    /vendors
  POST   /vendors                              (201)
  GET    /vendors/stats
  GET    /vendors/expiring                     (contracts expiring ≤ N days)
  GET    /vendors/{vendor_id}
  PATCH  /vendors/{vendor_id}
  DELETE /vendors/{vendor_id}                  (204)
  POST   /vendors/{vendor_id}/transition
  GET    /vendors/{vendor_id}/contacts
  POST   /vendors/{vendor_id}/contacts         (201)
  DELETE /vendors/{vendor_id}/contacts/{cid}  (204)
  GET    /vendors/{vendor_id}/reviews
  POST   /vendors/{vendor_id}/reviews          (201)
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
router = APIRouter(prefix="/vendors", tags=["vendor_management"])

_DB_PATH = str(Path(DATA_DIR) / "vendor_management.db")

_VEN_COLS = [
    "id", "name", "category", "status", "website",
    "contract_start", "contract_end", "contract_value",
    "sla_tier", "owner", "notes",
    "created_at", "updated_at",
]
_CON_COLS = ["id", "vendor_id", "name", "email", "phone", "role", "is_primary", "created_at"]
_REV_COLS = ["id", "vendor_id", "rating", "notes", "reviewer", "created_at"]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "active":       {"under_review", "suspended", "terminated"},
    "under_review": {"active",       "suspended", "terminated"},
    "suspended":    {"active",       "terminated"},
    "terminated":   set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_CATEGORIES = {"software", "hardware", "cloud", "consulting", "support", "other"}
_VALID_SLA_TIERS  = {"standard", "enhanced", "premium", ""}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS vendors (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            category       TEXT NOT NULL DEFAULT 'other',
            status         TEXT NOT NULL DEFAULT 'active',
            website        TEXT NOT NULL DEFAULT '',
            contract_start TEXT NOT NULL DEFAULT '',
            contract_end   TEXT NOT NULL DEFAULT '',
            contract_value REAL NOT NULL DEFAULT 0,
            sla_tier       TEXT NOT NULL DEFAULT '',
            owner          TEXT NOT NULL DEFAULT '',
            notes          TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vendor_contacts (
            id         TEXT PRIMARY KEY,
            vendor_id  TEXT NOT NULL,
            name       TEXT NOT NULL,
            email      TEXT NOT NULL DEFAULT '',
            phone      TEXT NOT NULL DEFAULT '',
            role       TEXT NOT NULL DEFAULT '',
            is_primary INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vendor_reviews (
            id         TEXT PRIMARY KEY,
            vendor_id  TEXT NOT NULL,
            rating     INTEGER NOT NULL,
            notes      TEXT NOT NULL DEFAULT '',
            reviewer   TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ven_status   ON vendors (status);
        CREATE INDEX IF NOT EXISTS idx_ven_category ON vendors (category);
        CREATE INDEX IF NOT EXISTS idx_ven_end      ON vendors (contract_end);
        CREATE INDEX IF NOT EXISTS idx_ven_sla      ON vendors (sla_tier);
        CREATE INDEX IF NOT EXISTS idx_ven_owner    ON vendors (owner);
        CREATE INDEX IF NOT EXISTS idx_con_vendor   ON vendor_contacts (vendor_id);
        CREATE INDEX IF NOT EXISTS idx_rev_vendor   ON vendor_reviews (vendor_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_ven_or_404(con: sqlite3.Connection, vendor_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_VEN_COLS)} FROM vendors WHERE id=?",
        (vendor_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Vendor not found")
    return row


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class VendorCreate(BaseModel):
    name:           str
    category:       str   = "other"
    website:        str   = ""
    contract_start: str   = ""
    contract_end:   str   = ""
    contract_value: float = 0.0
    sla_tier:       str   = ""
    owner:          str   = ""
    notes:          str   = ""

    @field_validator("contract_value")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("contract_value must be non-negative")
        return v


class VendorPatch(BaseModel):
    name:           Optional[str]   = None
    category:       Optional[str]   = None
    website:        Optional[str]   = None
    contract_start: Optional[str]   = None
    contract_end:   Optional[str]   = None
    contract_value: Optional[float] = None
    sla_tier:       Optional[str]   = None
    owner:          Optional[str]   = None
    notes:          Optional[str]   = None


class TransitionBody(BaseModel):
    status: str
    notes:  str = ""


class ContactCreate(BaseModel):
    name:       str
    email:      str = ""
    phone:      str = ""
    role:       str = ""
    is_primary: bool = False


class ReviewCreate(BaseModel):
    rating:   int
    notes:    str = ""
    reviewer: str = ""

    @field_validator("rating")
    @classmethod
    def valid_rating(cls, v: int) -> int:
        if v not in range(1, 6):
            raise ValueError("Rating must be 1-5")
        return v


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("", summary="List vendors")
async def list_vendors(
    q:        Optional[str] = Query(None),
    status:   Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(name LIKE ? OR website LIKE ? OR owner LIKE ? OR notes LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if category:
        where.append("category = ?"); params.append(category)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM vendors {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_VEN_COLS)} FROM vendors {clause} "
            "ORDER BY name ASC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "vendors": [dict(zip(_VEN_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("", status_code=201, summary="Create vendor")
async def create_vendor(body: VendorCreate, _auth=Depends(require_local_auth)):
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category '{body.category}'. Valid: {sorted(_VALID_CATEGORIES)}")
    ven_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO vendors ({','.join(_VEN_COLS)}) "
            f"VALUES ({','.join(['?']*len(_VEN_COLS))})",
            (ven_id, body.name, body.category, "active", body.website,
             body.contract_start, body.contract_end, body.contract_value,
             body.sla_tier, body.owner, body.notes, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": ven_id, "name": body.name, "status": "active"}


# ── Stats & expiring ──────────────────────────────────────────────────────────

@router.get("/stats", summary="Vendor statistics")
async def vendor_stats(_auth=Depends(require_local_auth)):
    try:
        con    = _conn()
        total  = con.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
        active = con.execute(
            "SELECT COUNT(*) FROM vendors WHERE status='active'"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM vendors GROUP BY status"
        ).fetchall()
        by_cat = con.execute(
            "SELECT category, COUNT(*) FROM vendors GROUP BY category ORDER BY COUNT(*) DESC"
        ).fetchall()
        expiring = con.execute(
            "SELECT COUNT(*) FROM vendors "
            "WHERE contract_end != '' AND status != 'terminated' "
            "AND date(contract_end) <= date('now','+30 days') "
            "AND date(contract_end) >= date('now')"
        ).fetchone()[0]
        avg_rating = con.execute(
            "SELECT ROUND(AVG(rating),2) FROM vendor_reviews"
        ).fetchone()[0]
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":       total,
        "active":      active,
        "expiring_30": expiring,
        "avg_rating":  avg_rating,
        "by_status":   [{"status": s, "count": c} for s, c in by_status],
        "by_category": [{"category": cat, "count": c} for cat, c in by_cat],
    }


@router.get("/expiring", summary="Vendors with contracts expiring soon")
async def expiring_vendors(
    days: int = Query(30, ge=1, le=365),
    _auth=Depends(require_local_auth),
):
    try:
        con  = _conn()
        rows = con.execute(
            f"SELECT {','.join(_VEN_COLS)} FROM vendors "
            "WHERE contract_end != '' AND status != 'terminated' "
            "AND date(contract_end) <= date('now', ? || ' days') "
            "AND date(contract_end) >= date('now') "
            "ORDER BY contract_end ASC LIMIT 500",
            (f"+{days}",),
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"vendors": [dict(zip(_VEN_COLS, r)) for r in rows], "days": days}


# ── Single vendor ─────────────────────────────────────────────────────────────

@router.get("/{vendor_id}", summary="Get vendor")
async def get_vendor(vendor_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_ven_or_404(con, vendor_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_VEN_COLS, row))


@router.patch("/{vendor_id}", summary="Update vendor")
async def patch_vendor(
    vendor_id: str, body: VendorPatch, _auth=Depends(require_local_auth)
):
    if body.category is not None and body.category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category '{body.category}'. Valid: {sorted(_VALID_CATEGORIES)}")
    if body.contract_value is not None and body.contract_value < 0:
        raise HTTPException(400, "contract_value must be non-negative")
    try:
        con = _conn()
        _get_ven_or_404(con, vendor_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "category", "website", "contract_start", "contract_end",
                      "contract_value", "sla_tier", "owner", "notes"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(vendor_id)
        con.execute(f"UPDATE vendors SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_VEN_COLS)} FROM vendors WHERE id=?",
            (vendor_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_VEN_COLS, row))


@router.delete("/{vendor_id}", status_code=204, summary="Delete vendor")
async def delete_vendor(vendor_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_ven_or_404(con, vendor_id)
        con.execute("DELETE FROM vendor_contacts WHERE vendor_id=?", (vendor_id,))
        con.execute("DELETE FROM vendor_reviews WHERE vendor_id=?", (vendor_id,))
        con.execute("DELETE FROM vendors WHERE id=?", (vendor_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/{vendor_id}/transition", summary="Transition vendor status")
async def transition_vendor(
    vendor_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_ven_or_404(con, vendor_id)
        d   = dict(zip(_VEN_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        now = _now()
        con.execute(
            "UPDATE vendors SET status=?, updated_at=? WHERE id=?",
            (body.status, now, vendor_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Contacts ──────────────────────────────────────────────────────────────────

@router.get("/{vendor_id}/contacts", summary="List vendor contacts")
async def list_contacts(vendor_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_ven_or_404(con, vendor_id)
        rows = con.execute(
            f"SELECT {','.join(_CON_COLS)} FROM vendor_contacts "
            "WHERE vendor_id=? ORDER BY is_primary DESC, created_at ASC LIMIT 50",
            (vendor_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"contacts": [dict(zip(_CON_COLS, r)) for r in rows]}


@router.post("/{vendor_id}/contacts", status_code=201, summary="Add vendor contact")
async def add_contact(
    vendor_id: str, body: ContactCreate, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_ven_or_404(con, vendor_id)
        con_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO vendor_contacts ({','.join(_CON_COLS)}) "
            f"VALUES ({','.join(['?']*len(_CON_COLS))})",
            (con_id, vendor_id, body.name, body.email, body.phone,
             body.role, 1 if body.is_primary else 0, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": con_id, "ok": True}


@router.delete("/{vendor_id}/contacts/{contact_id}", status_code=204,
               summary="Remove vendor contact")
async def delete_contact(
    vendor_id: str, contact_id: str, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_ven_or_404(con, vendor_id)
        row = con.execute(
            "SELECT id FROM vendor_contacts WHERE id=? AND vendor_id=?",
            (contact_id, vendor_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Contact not found")
        con.execute("DELETE FROM vendor_contacts WHERE id=?", (contact_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Reviews ───────────────────────────────────────────────────────────────────

@router.get("/{vendor_id}/reviews", summary="List vendor reviews")
async def list_reviews(vendor_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_ven_or_404(con, vendor_id)
        rows = con.execute(
            f"SELECT {','.join(_REV_COLS)} FROM vendor_reviews "
            "WHERE vendor_id=? ORDER BY created_at DESC LIMIT 200",
            (vendor_id,),
        ).fetchall()
        avg = con.execute(
            "SELECT ROUND(AVG(rating),2) FROM vendor_reviews WHERE vendor_id=?",
            (vendor_id,),
        ).fetchone()[0]
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "reviews":    [dict(zip(_REV_COLS, r)) for r in rows],
        "avg_rating": avg,
    }


@router.post("/{vendor_id}/reviews", status_code=201, summary="Add vendor review")
async def add_review(
    vendor_id: str, body: ReviewCreate, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_ven_or_404(con, vendor_id)
        rev_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO vendor_reviews ({','.join(_REV_COLS)}) "
            f"VALUES ({','.join(['?']*len(_REV_COLS))})",
            (rev_id, vendor_id, body.rating, body.notes, body.reviewer, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": rev_id, "ok": True}
