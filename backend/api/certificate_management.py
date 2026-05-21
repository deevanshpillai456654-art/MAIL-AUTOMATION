"""
Certificate Management
======================
SSL/TLS and code-signing certificate registry with renewal history,
expiry alerting and 6-state lifecycle.

Tables:
  certificates  — certificate records (domain, issuer, expiry, type)
  cert_renewals — renewal history (old_expires_at → new_expires_at)

State machine:
  pending  → active | cancelled
  active   → expiring | revoked | archived
  expiring → active  | expired  | revoked | archived
  expired  → active  | archived
  revoked  → (terminal)
  cancelled→ (terminal)
  archived → (terminal)

Computed at query time:
  days_until_expiry = (expires_at_date - today).days  (null if no expiry set)

POST /certificates/{id}/renew updates expires_at, resets status to 'active'
and logs a cert_renewal record.

Certificate types: ssl, wildcard, code_signing, email, client, ca

Endpoints:
  GET    /certificates
  POST   /certificates                            (201)
  GET    /certificates/stats
  GET    /certificates/expiring                   (?days=30)
  GET    /certificates/{cert_id}
  PATCH  /certificates/{cert_id}
  DELETE /certificates/{cert_id}                 (204)
  POST   /certificates/{cert_id}/transition
  GET    /certificates/{cert_id}/renewals
  POST   /certificates/{cert_id}/renew           (201)
"""
from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(tags=["certificate_management"])

_DB_PATH = str(Path(DATA_DIR) / "certificate_management.db")

_CERT_COLS = [
    "id", "name", "domain", "sans", "issuer", "type", "status",
    "environment", "thumbprint", "issued_at", "expires_at",
    "auto_renew", "owner", "team", "notes", "created_at", "updated_at",
]
_REN_COLS = [
    "id", "cert_id", "old_expires_at", "new_expires_at",
    "renewed_by", "notes", "created_at",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":   {"active", "cancelled"},
    "active":    {"expiring", "revoked", "archived"},
    "expiring":  {"active", "expired", "revoked", "archived"},
    "expired":   {"active", "archived"},
    "revoked":   set(),
    "cancelled": set(),
    "archived":  set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_TYPES = {"ssl", "wildcard", "code_signing", "email", "client", "ca"}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS certificates (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            domain      TEXT NOT NULL DEFAULT '',
            sans        TEXT NOT NULL DEFAULT '',
            issuer      TEXT NOT NULL DEFAULT '',
            type        TEXT NOT NULL DEFAULT 'ssl',
            status      TEXT NOT NULL DEFAULT 'pending',
            environment TEXT NOT NULL DEFAULT 'production',
            thumbprint  TEXT NOT NULL DEFAULT '',
            issued_at   TEXT NOT NULL DEFAULT '',
            expires_at  TEXT NOT NULL DEFAULT '',
            auto_renew  INTEGER NOT NULL DEFAULT 0,
            owner       TEXT NOT NULL DEFAULT '',
            team        TEXT NOT NULL DEFAULT '',
            notes       TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cert_renewals (
            id             TEXT PRIMARY KEY,
            cert_id        TEXT NOT NULL,
            old_expires_at TEXT NOT NULL DEFAULT '',
            new_expires_at TEXT NOT NULL DEFAULT '',
            renewed_by     TEXT NOT NULL DEFAULT '',
            notes          TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cert_status  ON certificates (status);
        CREATE INDEX IF NOT EXISTS idx_cert_type    ON certificates (type);
        CREATE INDEX IF NOT EXISTS idx_cert_domain  ON certificates (domain);
        CREATE INDEX IF NOT EXISTS idx_cert_expiry  ON certificates (expires_at);
        CREATE INDEX IF NOT EXISTS idx_cert_owner   ON certificates (owner);
        CREATE INDEX IF NOT EXISTS idx_cert_team    ON certificates (team);
        CREATE INDEX IF NOT EXISTS idx_cert_issuer  ON certificates (issuer);
        CREATE INDEX IF NOT EXISTS idx_cert_env     ON certificates (environment);
        CREATE INDEX IF NOT EXISTS idx_ren_cert     ON cert_renewals (cert_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_cert_or_404(con: sqlite3.Connection, cert_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_CERT_COLS)} FROM certificates WHERE id=?",
        (cert_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Certificate not found")
    return row


def _days_until_expiry(expires_at: str) -> Optional[int]:
    if not expires_at:
        return None
    try:
        exp = date.fromisoformat(expires_at[:10])
        return (exp - date.today()).days
    except ValueError:
        return None


def _enrich(d: dict) -> dict:
    return {**d, "days_until_expiry": _days_until_expiry(d.get("expires_at", ""))}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class CertCreate(BaseModel):
    name:        str
    domain:      str  = ""
    sans:        str  = ""
    issuer:      str  = ""
    type:        str  = "ssl"
    environment: str  = "production"
    thumbprint:  str  = ""
    issued_at:   str  = ""
    expires_at:  str  = ""
    auto_renew:  bool = False
    owner:       str  = ""
    team:        str  = ""
    notes:       str  = ""


class CertPatch(BaseModel):
    name:        Optional[str]  = None
    domain:      Optional[str]  = None
    sans:        Optional[str]  = None
    issuer:      Optional[str]  = None
    environment: Optional[str]  = None
    thumbprint:  Optional[str]  = None
    issued_at:   Optional[str]  = None
    expires_at:  Optional[str]  = None
    auto_renew:  Optional[bool] = None
    owner:       Optional[str]  = None
    team:        Optional[str]  = None
    notes:       Optional[str]  = None


class TransitionBody(BaseModel):
    status: str
    notes:  str = ""


class RenewBody(BaseModel):
    new_expires_at: str
    renewed_by:     str = ""
    notes:          str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("/certificates", summary="List certificates")
async def list_certificates(
    q:           Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    type:        Optional[str] = Query(None),
    environment: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append(
            "(name LIKE ? OR domain LIKE ? OR issuer LIKE ? OR owner LIKE ? OR sans LIKE ?)"
        )
        pct = f"%{q}%"
        params += [pct, pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if type:
        where.append("type = ?"); params.append(type)
    if environment:
        where.append("environment = ?"); params.append(environment)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM certificates {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_CERT_COLS)} FROM certificates {clause} "
            "ORDER BY expires_at ASC, created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "certificates": [_enrich(dict(zip(_CERT_COLS, r))) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("/certificates", status_code=201, summary="Create certificate")
async def create_certificate(body: CertCreate, _auth=Depends(require_local_auth)):
    if body.type not in _VALID_TYPES:
        raise HTTPException(
            400, f"Invalid type '{body.type}'. Valid: {sorted(_VALID_TYPES)}"
        )
    cert_id = str(uuid.uuid4())
    now     = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO certificates ({','.join(_CERT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_CERT_COLS))})",
            (cert_id, body.name, body.domain, body.sans, body.issuer, body.type,
             "pending", body.environment, body.thumbprint,
             body.issued_at, body.expires_at, int(body.auto_renew),
             body.owner, body.team, body.notes, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": cert_id, "name": body.name, "status": "pending"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/certificates/stats", summary="Certificate statistics")
async def cert_stats(_auth=Depends(require_local_auth)):
    try:
        con        = _conn()
        total      = con.execute("SELECT COUNT(*) FROM certificates").fetchone()[0]
        active     = con.execute(
            "SELECT COUNT(*) FROM certificates WHERE status='active'"
        ).fetchone()[0]
        expiring   = con.execute(
            "SELECT COUNT(*) FROM certificates WHERE status='expiring'"
        ).fetchone()[0]
        expired    = con.execute(
            "SELECT COUNT(*) FROM certificates WHERE status='expired'"
        ).fetchone()[0]
        revoked    = con.execute(
            "SELECT COUNT(*) FROM certificates WHERE status='revoked'"
        ).fetchone()[0]
        auto_renew = con.execute(
            "SELECT COUNT(*) FROM certificates WHERE auto_renew=1"
        ).fetchone()[0]
        expiring_30 = con.execute(
            "SELECT COUNT(*) FROM certificates "
            "WHERE expires_at != '' AND expires_at <= date('now', '+30 days') "
            "AND status NOT IN ('revoked','cancelled','archived')"
        ).fetchone()[0]
        by_type = con.execute(
            "SELECT type, COUNT(*) FROM certificates GROUP BY type ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM certificates GROUP BY status"
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":       total,
        "active":      active,
        "expiring":    expiring,
        "expired":     expired,
        "revoked":     revoked,
        "auto_renew":  auto_renew,
        "expiring_30": expiring_30,
        "by_type":     [{"type": t, "count": c} for t, c in by_type],
        "by_status":   [{"status": s, "count": c} for s, c in by_status],
    }


# ── Expiring ──────────────────────────────────────────────────────────────────

@router.get("/certificates/expiring", summary="Certificates expiring within N days")
async def expiring_certs(
    days: int = Query(30, ge=1, le=730),
    _auth=Depends(require_local_auth),
):
    interval = f"+{days} days"
    try:
        con  = _conn()
        rows = con.execute(
            f"SELECT {','.join(_CERT_COLS)} FROM certificates "
            "WHERE expires_at != '' "
            "  AND expires_at <= date('now', ?) "
            "  AND status NOT IN ('revoked','cancelled','archived') "
            "ORDER BY expires_at ASC LIMIT 500",
            (interval,),
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"certificates": [_enrich(dict(zip(_CERT_COLS, r))) for r in rows]}


# ── Single certificate ────────────────────────────────────────────────────────

@router.get("/certificates/{cert_id}", summary="Get certificate")
async def get_certificate(cert_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_cert_or_404(con, cert_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_CERT_COLS, row)))


@router.patch("/certificates/{cert_id}", summary="Update certificate")
async def patch_certificate(
    cert_id: str, body: CertPatch, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_cert_or_404(con, cert_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "domain", "sans", "issuer", "environment",
                      "thumbprint", "issued_at", "expires_at", "owner", "team", "notes"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        if body.auto_renew is not None:
            sets.append("auto_renew=?")
            params.append(int(body.auto_renew))
        params.append(cert_id)
        con.execute(f"UPDATE certificates SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_CERT_COLS)} FROM certificates WHERE id=?",
            (cert_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_CERT_COLS, row)))


@router.delete("/certificates/{cert_id}", status_code=204,
               summary="Delete certificate")
async def delete_certificate(cert_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_cert_or_404(con, cert_id)
        con.execute("DELETE FROM cert_renewals WHERE cert_id=?", (cert_id,))
        con.execute("DELETE FROM certificates   WHERE id=?",     (cert_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/certificates/{cert_id}/transition",
             summary="Transition certificate status")
async def transition_certificate(
    cert_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_cert_or_404(con, cert_id)
        d   = dict(zip(_CERT_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400,
                f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        con.execute(
            "UPDATE certificates SET status=?, updated_at=? WHERE id=?",
            (body.status, _now(), cert_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Renewals ──────────────────────────────────────────────────────────────────

@router.get("/certificates/{cert_id}/renewals", summary="List renewal history")
async def list_renewals(cert_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_cert_or_404(con, cert_id)
        rows = con.execute(
            f"SELECT {','.join(_REN_COLS)} FROM cert_renewals "
            "WHERE cert_id=? ORDER BY created_at DESC LIMIT 100",
            (cert_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"renewals": [dict(zip(_REN_COLS, r)) for r in rows]}


@router.post("/certificates/{cert_id}/renew", status_code=201,
             summary="Renew certificate — updates expiry and resets status to active")
async def renew_certificate(
    cert_id: str, body: RenewBody, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        row = _get_cert_or_404(con, cert_id)
        d   = dict(zip(_CERT_COLS, row))
        old_expires = d["expires_at"]
        ren_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO cert_renewals ({','.join(_REN_COLS)}) "
            f"VALUES ({','.join(['?']*len(_REN_COLS))})",
            (ren_id, cert_id, old_expires, body.new_expires_at,
             body.renewed_by, body.notes, now),
        )
        con.execute(
            "UPDATE certificates SET expires_at=?, status='active', updated_at=? WHERE id=?",
            (body.new_expires_at, now, cert_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "id": ren_id,
        "old_expires_at": old_expires,
        "new_expires_at": body.new_expires_at,
        "status": "active",
    }
