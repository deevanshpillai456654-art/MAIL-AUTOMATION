"""
Service Catalog
===============
Registry of business services with operational status, tier classification
and a full status-change history log.

Tables:
  services               — service record (name, slug, status, tier, owner…)
  service_status_history — immutable log of every status transition

Status values:
  operational | degraded | partial_outage | major_outage | maintenance | deprecated

Tier values:
  tier1 (critical) | tier2 (important) | tier3 (standard)

Endpoints:
  GET    /services
  POST   /services                              (201)
  GET    /services/stats
  GET    /services/{service_id}
  PATCH  /services/{service_id}
  DELETE /services/{service_id}
  POST   /services/{service_id}/status
  GET    /services/{service_id}/history
"""
from __future__ import annotations

import logging
import re
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
router = APIRouter(prefix="/services", tags=["service_catalog"])

_DB_PATH = str(Path(DATA_DIR) / "service_catalog.db")

_SVC_COLS = [
    "id", "name", "slug", "description", "status", "tier",
    "owner", "team", "documentation_url", "health_check_url",
    "created_at", "updated_at",
]
_HIST_COLS = [
    "id", "service_id", "previous_status", "new_status",
    "reason", "author", "changed_at",
]

_VALID_STATUSES = {
    "operational", "degraded", "partial_outage",
    "major_outage", "maintenance", "deprecated",
}
_VALID_TIERS = {"tier1", "tier2", "tier3"}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS services (
            id                TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            slug              TEXT NOT NULL UNIQUE,
            description       TEXT NOT NULL DEFAULT '',
            status            TEXT NOT NULL DEFAULT 'operational',
            tier              TEXT NOT NULL DEFAULT 'tier3',
            owner             TEXT NOT NULL DEFAULT '',
            team              TEXT NOT NULL DEFAULT '',
            documentation_url TEXT NOT NULL DEFAULT '',
            health_check_url  TEXT NOT NULL DEFAULT '',
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS service_status_history (
            id              TEXT PRIMARY KEY,
            service_id      TEXT NOT NULL,
            previous_status TEXT NOT NULL DEFAULT '',
            new_status      TEXT NOT NULL,
            reason          TEXT NOT NULL DEFAULT '',
            author          TEXT NOT NULL DEFAULT '',
            changed_at      TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_svc_status ON services (status);
        CREATE INDEX IF NOT EXISTS idx_svc_tier   ON services (tier);
        CREATE INDEX IF NOT EXISTS idx_ssh_service ON service_status_history (service_id, changed_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _unique_slug(con: sqlite3.Connection, base: str, exclude_id: str = "") -> str:
    slug, n = base, 0
    while True:
        row = con.execute(
            "SELECT id FROM services WHERE slug=?", (slug,)
        ).fetchone()
        if not row or (exclude_id and row[0] == exclude_id):
            return slug
        n += 1
        slug = f"{base}-{n}"


def _get_svc_or_404(con: sqlite3.Connection, service_id: str) -> tuple:
    # Accept id or slug
    row = con.execute(
        f"SELECT {','.join(_SVC_COLS)} FROM services WHERE id=? OR slug=?",
        (service_id, service_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Service not found")
    return row


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ServiceCreate(BaseModel):
    name:              str
    description:       str           = ""
    status:            str           = "operational"
    tier:              str           = "tier3"
    owner:             str           = ""
    team:              str           = ""
    documentation_url: str           = ""
    health_check_url:  str           = ""


class ServicePatch(BaseModel):
    name:              Optional[str] = None
    description:       Optional[str] = None
    tier:              Optional[str] = None
    owner:             Optional[str] = None
    team:              Optional[str] = None
    documentation_url: Optional[str] = None
    health_check_url:  Optional[str] = None


class StatusUpdate(BaseModel):
    status: str
    reason: str = ""
    author: str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("", summary="List services")
async def list_services(
    q:      Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tier:   Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(name LIKE ? OR description LIKE ? OR owner LIKE ? OR team LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if tier:
        where.append("tier = ?"); params.append(tier)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(f"SELECT COUNT(*) FROM services {clause}", params).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_SVC_COLS)} FROM services {clause} "
            "ORDER BY tier ASC, name ASC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {
        "services": [dict(zip(_SVC_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("", status_code=201, summary="Create service")
async def create_service(body: ServiceCreate, _auth=Depends(require_local_auth)):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(_VALID_STATUSES)}")
    if body.tier not in _VALID_TIERS:
        raise HTTPException(400, f"tier must be one of {sorted(_VALID_TIERS)}")
    svc_id = str(uuid.uuid4())
    now    = _now()
    try:
        con  = _conn()
        slug = _unique_slug(con, _slugify(body.name))
        con.execute(
            f"INSERT INTO services ({','.join(_SVC_COLS)}) "
            f"VALUES ({','.join(['?']*len(_SVC_COLS))})",
            (svc_id, body.name, slug, body.description, body.status, body.tier,
             body.owner, body.team, body.documentation_url, body.health_check_url,
             now, now),
        )
        # Seed initial status history
        con.execute(
            f"INSERT INTO service_status_history ({','.join(_HIST_COLS)}) "
            f"VALUES ({','.join(['?']*len(_HIST_COLS))})",
            (str(uuid.uuid4()), svc_id, "", body.status,
             "Service created.", body.owner or "system", now),
        )
        con.commit()
        con.close()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "A service with that slug already exists")
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"id": svc_id, "name": body.name, "slug": slug, "status": body.status}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Service catalog statistics")
async def service_stats(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        total      = con.execute("SELECT COUNT(*) FROM services").fetchone()[0]
        by_status  = con.execute(
            "SELECT status, COUNT(*) FROM services GROUP BY status"
        ).fetchall()
        by_tier    = con.execute(
            "SELECT tier, COUNT(*) FROM services GROUP BY tier"
        ).fetchall()
        degraded   = con.execute(
            "SELECT COUNT(*) FROM services WHERE status NOT IN ('operational','deprecated')"
        ).fetchone()[0]
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {
        "total": total,
        "degraded": degraded,
        "by_status": [{"status": s, "count": c} for s, c in by_status],
        "by_tier":   [{"tier":   t, "count": c} for t, c in by_tier],
    }


# ── Single service ────────────────────────────────────────────────────────────

@router.get("/{service_id}", summary="Get service by id or slug")
async def get_service(service_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_svc_or_404(con, service_id)
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return dict(zip(_SVC_COLS, row))


@router.patch("/{service_id}", summary="Update service metadata")
async def patch_service(
    service_id: str, body: ServicePatch, _auth=Depends(require_local_auth)
):
    if body.tier is not None and body.tier not in _VALID_TIERS:
        raise HTTPException(400, f"tier must be one of {sorted(_VALID_TIERS)}")
    try:
        con  = _conn()
        _get_svc_or_404(con, service_id)
        # Resolve real id if slug was passed
        real_id = con.execute(
            "SELECT id FROM services WHERE id=? OR slug=?", (service_id, service_id)
        ).fetchone()[0]
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "description", "tier", "owner", "team",
                      "documentation_url", "health_check_url"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        if body.name is not None:
            new_slug = _unique_slug(con, _slugify(body.name), exclude_id=real_id)
            sets.append("slug=?"); params.append(new_slug)
        params.append(real_id)
        con.execute(f"UPDATE services SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_SVC_COLS)} FROM services WHERE id=?", (real_id,)
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return dict(zip(_SVC_COLS, row))


@router.delete("/{service_id}", status_code=204, summary="Delete service")
async def delete_service(service_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_svc_or_404(con, service_id)
        real_id = row[0]
        con.execute("DELETE FROM service_status_history WHERE service_id=?", (real_id,))
        con.execute("DELETE FROM services WHERE id=?", (real_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")


# ── Status update ─────────────────────────────────────────────────────────────

@router.post("/{service_id}/status", summary="Update service status")
async def update_status(
    service_id: str, body: StatusUpdate, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(400, f"status must be one of {sorted(_VALID_STATUSES)}")
    try:
        con = _conn()
        row = _get_svc_or_404(con, service_id)
        real_id = row[0]
        prev_status = row[_SVC_COLS.index("status")]
        now = _now()
        con.execute(
            "UPDATE services SET status=?, updated_at=? WHERE id=?",
            (body.status, now, real_id),
        )
        con.execute(
            f"INSERT INTO service_status_history ({','.join(_HIST_COLS)}) "
            f"VALUES ({','.join(['?']*len(_HIST_COLS))})",
            (str(uuid.uuid4()), real_id, prev_status, body.status,
             body.reason, body.author, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"ok": True, "status": body.status}


# ── Status history ────────────────────────────────────────────────────────────

@router.get("/{service_id}/history", summary="Status change history")
async def get_history(
    service_id: str,
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        row = _get_svc_or_404(con, service_id)
        real_id = row[0]
        total = con.execute(
            "SELECT COUNT(*) FROM service_status_history WHERE service_id=?", (real_id,)
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_HIST_COLS)} FROM service_status_history "
            "WHERE service_id=? ORDER BY changed_at DESC LIMIT ? OFFSET ?",
            (real_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {
        "history": [dict(zip(_HIST_COLS, r)) for r in rows],
        "total": total,
    }
