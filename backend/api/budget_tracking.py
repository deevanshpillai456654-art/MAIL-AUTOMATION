"""
Budget & Cost Tracking
======================
Budget allocation registry with cost entry log, real-time spend
computation and 5-state lifecycle.

Tables:
  budgets      — budget allocations (amount, period, category)
  cost_entries — individual cost records linked to a budget

State machine:
  draft     → active | cancelled
  active    → frozen | closed
  frozen    → active | closed
  closed    → (terminal)
  cancelled → (terminal)

Spend is computed at query time as SUM(cost_entries.amount) for the
budget. `remaining` and `utilization_pct` are derived fields included
in single-budget GET and stats responses.

Categories: infrastructure, software, personnel, consulting,
            hardware, marketing, travel, other

Endpoints:
  GET    /budgets
  POST   /budgets                          (201)
  GET    /budgets/stats
  GET    /budgets/{budget_id}              (includes spent/remaining/pct)
  PATCH  /budgets/{budget_id}
  DELETE /budgets/{budget_id}              (204)
  POST   /budgets/{budget_id}/transition
  GET    /budgets/{budget_id}/entries
  POST   /budgets/{budget_id}/entries      (201)
  DELETE /budgets/{budget_id}/entries/{entry_id}  (204)
  GET    /cost_entries                     (global recent entries)
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
router = APIRouter(tags=["budget_tracking"])

_DB_PATH = str(Path(DATA_DIR) / "budget_tracking.db")

_BUD_COLS = [
    "id", "name", "category", "status",
    "period_start", "period_end", "amount", "currency",
    "owner", "team", "notes", "created_at", "updated_at",
]
_ENT_COLS = [
    "id", "budget_id", "amount", "description",
    "category", "vendor", "entry_date", "author", "created_at",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":     {"active", "cancelled"},
    "active":    {"frozen", "closed"},
    "frozen":    {"active", "closed"},
    "closed":    set(),
    "cancelled": set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_CATEGORIES = {
    "infrastructure", "software", "personnel", "consulting",
    "hardware", "marketing", "travel", "other",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS budgets (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            category     TEXT NOT NULL DEFAULT 'other',
            status       TEXT NOT NULL DEFAULT 'draft',
            period_start TEXT NOT NULL DEFAULT '',
            period_end   TEXT NOT NULL DEFAULT '',
            amount       REAL NOT NULL DEFAULT 0,
            currency     TEXT NOT NULL DEFAULT 'USD',
            owner        TEXT NOT NULL DEFAULT '',
            team         TEXT NOT NULL DEFAULT '',
            notes        TEXT NOT NULL DEFAULT '',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cost_entries (
            id          TEXT PRIMARY KEY,
            budget_id   TEXT NOT NULL,
            amount      REAL NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            category    TEXT NOT NULL DEFAULT '',
            vendor      TEXT NOT NULL DEFAULT '',
            entry_date  TEXT NOT NULL DEFAULT '',
            author      TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_bud_status   ON budgets (status);
        CREATE INDEX IF NOT EXISTS idx_bud_category ON budgets (category);
        CREATE INDEX IF NOT EXISTS idx_bud_period   ON budgets (period_start, period_end);
        CREATE INDEX IF NOT EXISTS idx_bud_owner    ON budgets (owner);
        CREATE INDEX IF NOT EXISTS idx_bud_team     ON budgets (team);
        CREATE INDEX IF NOT EXISTS idx_ent_budget   ON cost_entries (budget_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ent_date     ON cost_entries (entry_date DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_bud_or_404(con: sqlite3.Connection, budget_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_BUD_COLS)} FROM budgets WHERE id=?",
        (budget_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Budget not found")
    return row


def _get_spent(con: sqlite3.Connection, budget_id: str) -> float:
    row = con.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM cost_entries WHERE budget_id=?",
        (budget_id,),
    ).fetchone()
    return round(row[0], 2)


def _enrich(d: dict, spent: float) -> dict:
    amount = d.get("amount", 0) or 0
    remaining = round(amount - spent, 2)
    pct = round(spent / amount * 100, 2) if amount > 0 else 0.0
    return {**d, "spent": spent, "remaining": remaining, "utilization_pct": pct}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class BudgetCreate(BaseModel):
    name:         str
    category:     str   = "other"
    period_start: str   = ""
    period_end:   str   = ""
    amount:       float = 0.0
    currency:     str   = "USD"
    owner:        str   = ""
    team:         str   = ""
    notes:        str   = ""

    @field_validator("amount")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("amount must be non-negative")
        return v


class BudgetPatch(BaseModel):
    name:         Optional[str]   = None
    category:     Optional[str]   = None
    period_start: Optional[str]   = None
    period_end:   Optional[str]   = None
    amount:       Optional[float] = None
    currency:     Optional[str]   = None
    owner:        Optional[str]   = None
    team:         Optional[str]   = None
    notes:        Optional[str]   = None


class TransitionBody(BaseModel):
    status: str
    notes:  str = ""


class EntryCreate(BaseModel):
    amount:      float
    description: str = ""
    category:    str = ""
    vendor:      str = ""
    entry_date:  str = ""
    author:      str = ""

    @field_validator("amount")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("amount must be non-negative")
        return v


# ── Budgets list / create ─────────────────────────────────────────────────────

@router.get("/budgets", summary="List budgets")
async def list_budgets(
    q:        Optional[str] = Query(None),
    status:   Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(name LIKE ? OR owner LIKE ? OR team LIKE ? OR notes LIKE ?)")
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
            f"SELECT COUNT(*) FROM budgets {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_BUD_COLS)} FROM budgets {clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "budgets": [dict(zip(_BUD_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("/budgets", status_code=201, summary="Create budget")
async def create_budget(body: BudgetCreate, _auth=Depends(require_local_auth)):
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category '{body.category}'. Valid: {sorted(_VALID_CATEGORIES)}")
    bud_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO budgets ({','.join(_BUD_COLS)}) "
            f"VALUES ({','.join(['?']*len(_BUD_COLS))})",
            (bud_id, body.name, body.category, "draft",
             body.period_start, body.period_end, body.amount, body.currency,
             body.owner, body.team, body.notes, now, now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": bud_id, "name": body.name, "status": "draft"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/budgets/stats", summary="Budget & cost statistics")
async def budget_stats(_auth=Depends(require_local_auth)):
    try:
        con         = _conn()
        total       = con.execute("SELECT COUNT(*) FROM budgets").fetchone()[0]
        active      = con.execute(
            "SELECT COUNT(*) FROM budgets WHERE status='active'"
        ).fetchone()[0]
        total_alloc = con.execute(
            "SELECT COALESCE(SUM(amount),0) FROM budgets WHERE status='active'"
        ).fetchone()[0]
        total_spent = con.execute(
            "SELECT COALESCE(SUM(ce.amount),0) FROM cost_entries ce "
            "JOIN budgets b ON ce.budget_id=b.id WHERE b.status='active'"
        ).fetchone()[0]
        over_budget = con.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT b.id FROM budgets b "
            "  JOIN cost_entries ce ON ce.budget_id=b.id "
            "  WHERE b.status='active' "
            "  GROUP BY b.id HAVING SUM(ce.amount) > b.amount"
            ")"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM budgets GROUP BY status"
        ).fetchall()
        by_cat = con.execute(
            "SELECT category, COUNT(*) FROM budgets "
            "GROUP BY category ORDER BY COUNT(*) DESC"
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":         total,
        "active":        active,
        "total_allocated": round(total_alloc, 2),
        "total_spent":   round(total_spent, 2),
        "over_budget":   over_budget,
        "by_status":     [{"status": s, "count": c} for s, c in by_status],
        "by_category":   [{"category": cat, "count": c} for cat, c in by_cat],
    }


# ── Single budget ─────────────────────────────────────────────────────────────

@router.get("/budgets/{budget_id}", summary="Get budget with spend summary")
async def get_budget(budget_id: str, _auth=Depends(require_local_auth)):
    try:
        con  = _conn()
        row  = _get_bud_or_404(con, budget_id)
        spent = _get_spent(con, budget_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_BUD_COLS, row)), spent)


@router.patch("/budgets/{budget_id}", summary="Update budget")
async def patch_budget(
    budget_id: str, body: BudgetPatch, _auth=Depends(require_local_auth)
):
    if body.category is not None and body.category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"Invalid category. Valid: {sorted(_VALID_CATEGORIES)}")
    if body.amount is not None and body.amount < 0:
        raise HTTPException(400, "amount must be non-negative")
    try:
        con = _conn()
        _get_bud_or_404(con, budget_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "category", "period_start", "period_end",
                      "amount", "currency", "owner", "team", "notes"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(budget_id)
        con.execute(f"UPDATE budgets SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row   = con.execute(
            f"SELECT {','.join(_BUD_COLS)} FROM budgets WHERE id=?",
            (budget_id,),
        ).fetchone()
        spent = _get_spent(con, budget_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return _enrich(dict(zip(_BUD_COLS, row)), spent)


@router.delete("/budgets/{budget_id}", status_code=204, summary="Delete budget")
async def delete_budget(budget_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_bud_or_404(con, budget_id)
        con.execute("DELETE FROM cost_entries WHERE budget_id=?", (budget_id,))
        con.execute("DELETE FROM budgets WHERE id=?", (budget_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/budgets/{budget_id}/transition", summary="Transition budget status")
async def transition_budget(
    budget_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_bud_or_404(con, budget_id)
        d   = dict(zip(_BUD_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        now = _now()
        con.execute(
            "UPDATE budgets SET status=?, updated_at=? WHERE id=?",
            (body.status, now, budget_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Cost entries ──────────────────────────────────────────────────────────────

@router.get("/budgets/{budget_id}/entries", summary="List cost entries for budget")
async def list_entries(
    budget_id: str,
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_bud_or_404(con, budget_id)
        total = con.execute(
            "SELECT COUNT(*) FROM cost_entries WHERE budget_id=?", (budget_id,)
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_ENT_COLS)} FROM cost_entries "
            "WHERE budget_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (budget_id, limit, offset),
        ).fetchall()
        spent = _get_spent(con, budget_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "entries": [dict(zip(_ENT_COLS, r)) for r in rows],
        "total": total, "spent": spent,
    }


@router.post("/budgets/{budget_id}/entries", status_code=201,
             summary="Add cost entry to budget")
async def add_entry(
    budget_id: str, body: EntryCreate, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_bud_or_404(con, budget_id)
        ent_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO cost_entries ({','.join(_ENT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_ENT_COLS))})",
            (ent_id, budget_id, body.amount, body.description,
             body.category, body.vendor, body.entry_date, body.author, now),
        )
        con.execute(
            "UPDATE budgets SET updated_at=? WHERE id=?", (now, budget_id)
        )
        spent = _get_spent(con, budget_id)
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": ent_id, "spent": spent, "ok": True}


@router.delete("/budgets/{budget_id}/entries/{entry_id}", status_code=204,
               summary="Delete cost entry")
async def delete_entry(
    budget_id: str, entry_id: str, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_bud_or_404(con, budget_id)
        row = con.execute(
            "SELECT id FROM cost_entries WHERE id=? AND budget_id=?",
            (entry_id, budget_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Cost entry not found")
        con.execute("DELETE FROM cost_entries WHERE id=?", (entry_id,))
        con.execute(
            "UPDATE budgets SET updated_at=? WHERE id=?", (_now(), budget_id)
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Global recent entries ─────────────────────────────────────────────────────

@router.get("/cost_entries", summary="Recent cost entries across all budgets")
async def recent_entries(
    limit: int = Query(50, ge=1, le=500),
    _auth=Depends(require_local_auth),
):
    try:
        con  = _conn()
        rows = con.execute(
            f"SELECT {','.join(_ENT_COLS)} FROM cost_entries "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"entries": [dict(zip(_ENT_COLS, r)) for r in rows]}
