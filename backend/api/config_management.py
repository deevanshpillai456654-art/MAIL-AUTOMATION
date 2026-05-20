"""
Configuration Management
========================
Versioned key-value config store with per-environment scoping, type
validation and environment promotion.

Tables:
  config_items    — config records (key unique per environment, typed value)
  config_versions — immutable history of every value change

State machine:
  active     → deprecated | archived
  deprecated → active    | archived
  archived   → (terminal)

UNIQUE constraint: (key, environment) → 409 on duplicate.
Every value change via PATCH appends a config_version row.
Initial value is seeded as version 1 on create.

Config types: string, number, boolean, json, secret

Endpoints:
  GET    /configs
  POST   /configs                             (201, 409 on dup key+env)
  GET    /configs/stats
  GET    /configs/{config_id}
  PATCH  /configs/{config_id}
  DELETE /configs/{config_id}               (204)
  POST   /configs/{config_id}/transition
  GET    /configs/{config_id}/versions
  POST   /configs/{config_id}/promote       (201, 409 if already in target env)
"""
from __future__ import annotations

import logging
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
router = APIRouter(tags=["config_management"])

_DB_PATH = str(Path(DATA_DIR) / "config_management.db")

_CFG_COLS = [
    "id", "key", "value", "environment", "type", "description",
    "status", "owner", "team", "tags", "created_at", "updated_at",
]
_VER_COLS = [
    "id", "config_id", "value", "changed_by", "note", "created_at",
]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "active":     {"deprecated", "archived"},
    "deprecated": {"active", "archived"},
    "archived":   set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_TYPES = {"string", "number", "boolean", "json", "secret"}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS config_items (
            id          TEXT PRIMARY KEY,
            key         TEXT NOT NULL,
            value       TEXT NOT NULL DEFAULT '',
            environment TEXT NOT NULL DEFAULT 'production',
            type        TEXT NOT NULL DEFAULT 'string',
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'active',
            owner       TEXT NOT NULL DEFAULT '',
            team        TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            UNIQUE (key, environment)
        );

        CREATE TABLE IF NOT EXISTS config_versions (
            id         TEXT PRIMARY KEY,
            config_id  TEXT NOT NULL,
            value      TEXT NOT NULL DEFAULT '',
            changed_by TEXT NOT NULL DEFAULT '',
            note       TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_cfg_env    ON config_items (environment);
        CREATE INDEX IF NOT EXISTS idx_cfg_status ON config_items (status);
        CREATE INDEX IF NOT EXISTS idx_cfg_type   ON config_items (type);
        CREATE INDEX IF NOT EXISTS idx_ver_cfg    ON config_versions (config_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_cfg_or_404(con: sqlite3.Connection, config_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_CFG_COLS)} FROM config_items WHERE id=?",
        (config_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Config not found")
    return row


def _version_count(con: sqlite3.Connection, config_id: str) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM config_versions WHERE config_id=?", (config_id,)
    ).fetchone()[0]


def _add_version(
    con: sqlite3.Connection, config_id: str, value: str,
    changed_by: str = "", note: str = "",
) -> None:
    con.execute(
        f"INSERT INTO config_versions ({','.join(_VER_COLS)}) "
        f"VALUES ({','.join(['?']*len(_VER_COLS))})",
        (str(uuid.uuid4()), config_id, value, changed_by, note, _now()),
    )


def _enrich(d: dict, con: sqlite3.Connection) -> dict:
    return {**d, "version_count": _version_count(con, d["id"])}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ConfigCreate(BaseModel):
    key:         str
    value:       str   = ""
    environment: str   = "production"
    type:        str   = "string"
    description: str   = ""
    owner:       str   = ""
    team:        str   = ""
    tags:        str   = ""
    changed_by:  str   = ""


class ConfigPatch(BaseModel):
    value:       Optional[str] = None
    description: Optional[str] = None
    owner:       Optional[str] = None
    team:        Optional[str] = None
    tags:        Optional[str] = None
    changed_by:  str           = ""
    note:        str           = ""


class TransitionBody(BaseModel):
    status: str
    note:   str = ""


class PromoteBody(BaseModel):
    target_environment: str
    changed_by:         str = ""
    note:               str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("/configs", summary="List config items")
async def list_configs(
    q:           Optional[str] = Query(None),
    environment: Optional[str] = Query(None),
    type:        Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append(
            "(key LIKE ? OR description LIKE ? OR owner LIKE ? OR tags LIKE ?)"
        )
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if environment:
        where.append("environment = ?"); params.append(environment)
    if type:
        where.append("type = ?"); params.append(type)
    if status:
        where.append("status = ?"); params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM config_items {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_CFG_COLS)} FROM config_items {clause} "
            "ORDER BY environment, key ASC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        result = [_enrich(dict(zip(_CFG_COLS, r)), con) for r in rows]
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"configs": result, "total": total, "limit": limit, "offset": offset}


@router.post("/configs", status_code=201, summary="Create config item")
async def create_config(body: ConfigCreate, _auth=Depends(require_local_auth)):
    if body.type not in _VALID_TYPES:
        raise HTTPException(
            400, f"Invalid type '{body.type}'. Valid: {sorted(_VALID_TYPES)}"
        )
    cfg_id = str(uuid.uuid4())
    now    = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO config_items ({','.join(_CFG_COLS)}) "
            f"VALUES ({','.join(['?']*len(_CFG_COLS))})",
            (cfg_id, body.key, body.value, body.environment, body.type,
             body.description, "active", body.owner, body.team, body.tags,
             now, now),
        )
        _add_version(con, cfg_id, body.value, body.changed_by, "initial value")
        con.commit()
        con.close()
    except sqlite3.IntegrityError:
        raise HTTPException(
            409, f"Config key '{body.key}' already exists in environment '{body.environment}'"
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": cfg_id, "key": body.key, "environment": body.environment, "status": "active"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/configs/stats", summary="Config statistics")
async def config_stats(_auth=Depends(require_local_auth)):
    try:
        con        = _conn()
        total      = con.execute("SELECT COUNT(*) FROM config_items").fetchone()[0]
        active     = con.execute(
            "SELECT COUNT(*) FROM config_items WHERE status='active'"
        ).fetchone()[0]
        deprecated = con.execute(
            "SELECT COUNT(*) FROM config_items WHERE status='deprecated'"
        ).fetchone()[0]
        by_env = con.execute(
            "SELECT environment, COUNT(*) FROM config_items "
            "GROUP BY environment ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_type = con.execute(
            "SELECT type, COUNT(*) FROM config_items "
            "GROUP BY type ORDER BY COUNT(*) DESC"
        ).fetchall()
        total_versions = con.execute(
            "SELECT COUNT(*) FROM config_versions"
        ).fetchone()[0]
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":          total,
        "active":         active,
        "deprecated":     deprecated,
        "total_versions": total_versions,
        "by_environment": [{"environment": e, "count": c} for e, c in by_env],
        "by_type":        [{"type": t, "count": c} for t, c in by_type],
    }


# ── Single config ─────────────────────────────────────────────────────────────

@router.get("/configs/{config_id}", summary="Get config item")
async def get_config(config_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_cfg_or_404(con, config_id)
        d   = _enrich(dict(zip(_CFG_COLS, row)), con)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return d


@router.patch("/configs/{config_id}", summary="Update config item")
async def patch_config(
    config_id: str, body: ConfigPatch, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        row = _get_cfg_or_404(con, config_id)
        d   = dict(zip(_CFG_COLS, row))
        sets, params = ["updated_at=?"], [_now()]
        new_value = None
        for field in ("value", "description", "owner", "team", "tags"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
                if field == "value" and val != d["value"]:
                    new_value = val
        params.append(config_id)
        con.execute(f"UPDATE config_items SET {','.join(sets)} WHERE id=?", params)
        if new_value is not None:
            _add_version(con, config_id, new_value, body.changed_by, body.note)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_CFG_COLS)} FROM config_items WHERE id=?",
            (config_id,),
        ).fetchone()
        d = _enrich(dict(zip(_CFG_COLS, row)), con)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return d


@router.delete("/configs/{config_id}", status_code=204, summary="Delete config item")
async def delete_config(config_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_cfg_or_404(con, config_id)
        con.execute("DELETE FROM config_versions WHERE config_id=?", (config_id,))
        con.execute("DELETE FROM config_items    WHERE id=?",         (config_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/configs/{config_id}/transition", summary="Transition config status")
async def transition_config(
    config_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_cfg_or_404(con, config_id)
        d   = dict(zip(_CFG_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        con.execute(
            "UPDATE config_items SET status=?, updated_at=? WHERE id=?",
            (body.status, _now(), config_id),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Versions ──────────────────────────────────────────────────────────────────

@router.get("/configs/{config_id}/versions", summary="List config version history")
async def list_versions(
    config_id: str,
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_cfg_or_404(con, config_id)
        total = con.execute(
            "SELECT COUNT(*) FROM config_versions WHERE config_id=?", (config_id,)
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_VER_COLS)} FROM config_versions "
            "WHERE config_id=? ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (config_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "versions": [dict(zip(_VER_COLS, r)) for r in rows],
        "total": total,
    }


# ── Promote ───────────────────────────────────────────────────────────────────

@router.post("/configs/{config_id}/promote", status_code=201,
             summary="Promote config to another environment")
async def promote_config(
    config_id: str, body: PromoteBody, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        row = _get_cfg_or_404(con, config_id)
        src = dict(zip(_CFG_COLS, row))
        new_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO config_items ({','.join(_CFG_COLS)}) "
            f"VALUES ({','.join(['?']*len(_CFG_COLS))})",
            (new_id, src["key"], src["value"], body.target_environment,
             src["type"], src["description"], "active",
             src["owner"], src["team"], src["tags"], now, now),
        )
        note = body.note or f"Promoted from '{src['environment']}'"
        _add_version(con, new_id, src["value"], body.changed_by, note)
        con.commit()
        con.close()
    except sqlite3.IntegrityError:
        raise HTTPException(
            409,
            f"Config key '{src['key']}' already exists in environment "
            f"'{body.target_environment}'"
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "id": new_id,
        "key": src["key"],
        "environment": body.target_environment,
        "status": "active",
    }
