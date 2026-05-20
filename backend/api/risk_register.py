"""
Risk Register
=============
Enterprise risk tracking with likelihood × impact scoring, auto-computed
risk level, review history and 6-state mitigation lifecycle.

Tables:
  risks        — risk records (likelihood 1-5, impact 1-5)
  risk_reviews — periodic review snapshots (updates likelihood/impact on risk)

Computed at query time:
  risk_score = likelihood * impact          (1-25)
  risk_level = critical(≥15) | high(≥10) | medium(≥5) | low(<5)

State machine:
  identified → assessed  | closed
  assessed   → mitigating | accepted | closed
  mitigating → resolved   | accepted | closed
  accepted   → mitigating | closed
  resolved   → closed     | identified
  closed     → (terminal)

Categories: technical, operational, financial, legal,
            strategic, security, compliance, environmental

POST /risks/{id}/reviews creates a review snapshot and updates the
risk's current likelihood and impact to the reviewed values.

Endpoints:
  GET    /risks
  POST   /risks                          (201)
  GET    /risks/stats
  GET    /risks/{risk_id}
  PATCH  /risks/{risk_id}
  DELETE /risks/{risk_id}               (204)
  POST   /risks/{risk_id}/transition
  GET    /risks/{risk_id}/reviews
  POST   /risks/{risk_id}/reviews       (201)
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
router = APIRouter(tags=["risk_register"])

_DB_PATH = str(Path(DATA_DIR) / "risk_register.db")

_RISK_COLS = [
    "id", "title", "description", "category", "likelihood", "impact",
    "status", "owner", "team", "mitigation_plan", "review_date",
    "tags", "created_at", "updated_at",
]
_REV_COLS = [
    "id", "risk_id", "likelihood", "impact", "notes", "reviewer", "created_at",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "identified": {"assessed", "closed"},
    "assessed":   {"mitigating", "accepted", "closed"},
    "mitigating": {"resolved", "accepted", "closed"},
    "accepted":   {"mitigating", "closed"},
    "resolved":   {"closed", "identified"},
    "closed":     set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_CATEGORIES = {
    "technical", "operational", "financial", "legal",
    "strategic", "security", "compliance", "environmental",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS risks (
            id               TEXT PRIMARY KEY,
            title            TEXT NOT NULL,
            description      TEXT NOT NULL DEFAULT '',
            category         TEXT NOT NULL DEFAULT 'operational',
            likelihood       INTEGER NOT NULL DEFAULT 3,
            impact           INTEGER NOT NULL DEFAULT 3,
            status           TEXT NOT NULL DEFAULT 'identified',
            owner            TEXT NOT NULL DEFAULT '',
            team             TEXT NOT NULL DEFAULT '',
            mitigation_plan  TEXT NOT NULL DEFAULT '',
            review_date      TEXT NOT NULL DEFAULT '',
            tags             TEXT NOT NULL DEFAULT '',
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS risk_reviews (
            id         TEXT PRIMARY KEY,
            risk_id    TEXT NOT NULL,
            likelihood INTEGER NOT NULL DEFAULT 3,
            impact     INTEGER NOT NULL DEFAULT 3,
            notes      TEXT NOT NULL DEFAULT '',
            reviewer   TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_risk_status   ON risks (status);
        CREATE INDEX IF NOT EXISTS idx_risk_category ON risks (category);
        CREATE INDEX IF NOT EXISTS idx_risk_score    ON risks (likelihood * impact DESC);
        CREATE INDEX IF NOT EXISTS idx_rev_risk      ON risk_reviews (risk_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_risk_or_404(con: sqlite3.Connection, risk_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_RISK_COLS)} FROM risks WHERE id=?",
        (risk_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Risk not found")
    return row


def _risk_level(score: int) -> str:
    if score >= 15:
        return "critical"
    if score >= 10:
        return "high"
    if score >= 5:
        return "medium"
    return "low"


def _enrich(d: dict) -> dict:
    score = (d.get("likelihood") or 1) * (d.get("impact") or 1)
    return {**d, "risk_score": score, "risk_level": _risk_level(score)}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RiskCreate(BaseModel):
    title:           str
    description:     str = ""
    category:        str = "operational"
    likelihood:      int = 3
    impact:          int = 3
    owner:           str = ""
    team:            str = ""
    mitigation_plan: str = ""
    review_date:     str = ""
    tags:            str = ""

    @field_validator("likelihood", "impact")
    @classmethod
    def must_be_1_to_5(cls, v: int) -> int:
        if not (1 <= v <= 5):
            raise ValueError("must be between 1 and 5")
        return v


class RiskPatch(BaseModel):
    title:           Optional[str] = None
    description:     Optional[str] = None
    category:        Optional[str] = None
    likelihood:      Optional[int] = None
    impact:          Optional[int] = None
    owner:           Optional[str] = None
    team:            Optional[str] = None
    mitigation_plan: Optional[str] = None
    review_date:     Optional[str] = None
    tags:            Optional[str] = None

    @field_validator("likelihood", "impact")
    @classmethod
    def must_be_1_to_5(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 5):
            raise ValueError("must be between 1 and 5")
        return v


class TransitionBody(BaseModel):
    status: str
    notes:  str = ""


class ReviewCreate(BaseModel):
    likelihood: int = 3
    impact:     int = 3
    notes:      str = ""
    reviewer:   str = ""

    @field_validator("likelihood", "impact")
    @classmethod
    def must_be_1_to_5(cls, v: int) -> int:
        if not (1 <= v <= 5):
            raise ValueError("must be between 1 and 5")
        return v


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("/risks", summary="List risks")
async def list_risks(
    q:        Optional[str] = Query(None),
    status:   Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    level:    Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append(
            "(title LIKE ? OR description LIKE ? OR owner LIKE ? OR tags LIKE ?)"
        )
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    if category:
        where.append("category = ?"); params.append(category)
    if level:
        if level == "critical":
            where.append("likelihood * impact >= 15")
        elif level == "high":
            where.append("likelihood * impact >= 10 AND likelihood * impact < 15")
        elif level == "medium":
            where.append("likelihood * impact >= 5 AND likelihood * impact < 10")
        elif level == "low":
            where.append("likelihood * impact < 5")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM risks {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_RISK_COLS)} FROM risks {clause} "
            "ORDER BY likelihood * impact DESC, created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "risks": [_enrich(dict(zip(_RISK_COLS, r))) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("/risks", status_code=201, summary="Create risk")
async def create_risk(body: RiskCreate, _auth=Depends(require_local_auth)):
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(
            400, f"Invalid category '{body.category}'. Valid: {sorted(_VALID_CATEGORIES)}"
        )
    risk_id = str(uuid.uuid4())
    now     = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO risks ({','.join(_RISK_COLS)}) "
            f"VALUES ({','.join(['?']*len(_RISK_COLS))})",
            (risk_id, body.title, body.description, body.category,
             body.likelihood, body.impact, "identified",
             body.owner, body.team, body.mitigation_plan,
             body.review_date, body.tags, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    score = body.likelihood * body.impact
    return {
        "id": risk_id, "title": body.title, "status": "identified",
        "risk_score": score, "risk_level": _risk_level(score),
    }


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/risks/stats", summary="Risk statistics")
async def risk_stats(_auth=Depends(require_local_auth)):
    try:
        con       = _conn()
        total     = con.execute("SELECT COUNT(*) FROM risks").fetchone()[0]
        critical  = con.execute(
            "SELECT COUNT(*) FROM risks WHERE likelihood * impact >= 15"
        ).fetchone()[0]
        high      = con.execute(
            "SELECT COUNT(*) FROM risks "
            "WHERE likelihood * impact >= 10 AND likelihood * impact < 15"
        ).fetchone()[0]
        open_count = con.execute(
            "SELECT COUNT(*) FROM risks WHERE status != 'closed'"
        ).fetchone()[0]
        avg_score = con.execute(
            "SELECT AVG(likelihood * impact) FROM risks"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM risks GROUP BY status"
        ).fetchall()
        by_cat = con.execute(
            "SELECT category, COUNT(*) FROM risks "
            "GROUP BY category ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_level = con.execute(
            "SELECT "
            "  SUM(CASE WHEN likelihood*impact >= 15 THEN 1 ELSE 0 END), "
            "  SUM(CASE WHEN likelihood*impact >= 10 AND likelihood*impact < 15 THEN 1 ELSE 0 END), "
            "  SUM(CASE WHEN likelihood*impact >= 5  AND likelihood*impact < 10 THEN 1 ELSE 0 END), "
            "  SUM(CASE WHEN likelihood*impact < 5 THEN 1 ELSE 0 END) "
            "FROM risks"
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":      total,
        "open":       open_count,
        "critical":   critical,
        "high":       high,
        "avg_score":  round(avg_score, 2) if avg_score else 0.0,
        "by_status":  [{"status": s, "count": c} for s, c in by_status],
        "by_category": [{"category": cat, "count": c} for cat, c in by_cat],
        "by_level":   {
            "critical": by_level[0] or 0,
            "high":     by_level[1] or 0,
            "medium":   by_level[2] or 0,
            "low":      by_level[3] or 0,
        },
    }


# ── Single risk ───────────────────────────────────────────────────────────────

@router.get("/risks/{risk_id}", summary="Get risk")
async def get_risk(risk_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_risk_or_404(con, risk_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_RISK_COLS, row)))


@router.patch("/risks/{risk_id}", summary="Update risk")
async def patch_risk(
    risk_id: str, body: RiskPatch, _auth=Depends(require_local_auth)
):
    if body.category is not None and body.category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category. Valid: {sorted(_VALID_CATEGORIES)}")
    try:
        con = _conn()
        _get_risk_or_404(con, risk_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("title", "description", "category", "likelihood", "impact",
                      "owner", "team", "mitigation_plan", "review_date", "tags"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(risk_id)
        con.execute(f"UPDATE risks SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_RISK_COLS)} FROM risks WHERE id=?", (risk_id,)
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_RISK_COLS, row)))


@router.delete("/risks/{risk_id}", status_code=204, summary="Delete risk")
async def delete_risk(risk_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_risk_or_404(con, risk_id)
        con.execute("DELETE FROM risk_reviews WHERE risk_id=?", (risk_id,))
        con.execute("DELETE FROM risks        WHERE id=?",      (risk_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/risks/{risk_id}/transition", summary="Transition risk status")
async def transition_risk(
    risk_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_risk_or_404(con, risk_id)
        d   = dict(zip(_RISK_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        con.execute(
            "UPDATE risks SET status=?, updated_at=? WHERE id=?",
            (body.status, _now(), risk_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Reviews ───────────────────────────────────────────────────────────────────

@router.get("/risks/{risk_id}/reviews", summary="List review history")
async def list_reviews(risk_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_risk_or_404(con, risk_id)
        rows = con.execute(
            f"SELECT {','.join(_REV_COLS)} FROM risk_reviews "
            "WHERE risk_id=? ORDER BY created_at DESC",
            (risk_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"reviews": [dict(zip(_REV_COLS, r)) for r in rows]}


@router.post("/risks/{risk_id}/reviews", status_code=201,
             summary="Add risk review — updates likelihood and impact on parent risk")
async def add_review(
    risk_id: str, body: ReviewCreate, _auth=Depends(require_local_auth)
):
    try:
        con    = _conn()
        _get_risk_or_404(con, risk_id)
        rev_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO risk_reviews ({','.join(_REV_COLS)}) "
            f"VALUES ({','.join(['?']*len(_REV_COLS))})",
            (rev_id, risk_id, body.likelihood, body.impact,
             body.notes, body.reviewer, now),
        )
        con.execute(
            "UPDATE risks SET likelihood=?, impact=?, updated_at=? WHERE id=?",
            (body.likelihood, body.impact, now, risk_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    score = body.likelihood * body.impact
    return {
        "id": rev_id, "risk_score": score,
        "risk_level": _risk_level(score), "ok": True,
    }
