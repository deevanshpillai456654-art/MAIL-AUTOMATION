"""
Feature Flags
=============
Flag registry with per-environment enablement, rollout percentage (0-100),
4-state lifecycle and an immutable event log.

Tables:
  feature_flags     — flag definitions (key UNIQUE)
  flag_environments — per-environment state (UNIQUE flag_id + environment)
  flag_events       — append-only audit log

State machine:
  draft      → active | archived
  active     → deprecated | archived
  deprecated → active   | archived
  archived   → (terminal)

Key: auto-generated snake_case slug from name; unique, enforced on create.

Environment record: upsert semantics — POST creates or updates the row for
  a given (flag_id, environment) pair. enabled and rollout_pct (0-100)
  are validated on write.

Event types: created, enabled, disabled, rollout_changed,
             status_changed, note

Endpoints:
  GET    /flags
  POST   /flags                              (201)
  GET    /flags/stats
  GET    /flags/{flag_id}
  PATCH  /flags/{flag_id}
  DELETE /flags/{flag_id}                    (204)
  POST   /flags/{flag_id}/transition
  GET    /flags/{flag_id}/environments
  POST   /flags/{flag_id}/environments       (upsert, 200/201)
  GET    /flags/{flag_id}/events
  POST   /flags/{flag_id}/events             (201)
"""
from __future__ import annotations

import logging
import re
import sqlite3
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/flags", tags=["feature_flags"])

_DB_PATH = str(Path(DATA_DIR) / "feature_flags.db")

_FLAG_COLS = [
    "id", "name", "key", "description", "status",
    "owner", "tags", "created_at", "updated_at",
]
_ENV_COLS = [
    "id", "flag_id", "environment", "enabled",
    "rollout_pct", "notes", "updated_at",
]
_EVT_COLS = ["id", "flag_id", "event_type", "note", "author", "created_at"]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":      {"active", "archived"},
    "active":     {"deprecated", "archived"},
    "deprecated": {"active", "archived"},
    "archived":   set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_EVENT_TYPES = {
    "created", "enabled", "disabled", "rollout_changed", "status_changed", "note",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS feature_flags (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            key         TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'draft',
            owner       TEXT NOT NULL DEFAULT '',
            tags        TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS flag_environments (
            id          TEXT PRIMARY KEY,
            flag_id     TEXT NOT NULL,
            environment TEXT NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 0,
            rollout_pct REAL    NOT NULL DEFAULT 0,
            notes       TEXT    NOT NULL DEFAULT '',
            updated_at  TEXT    NOT NULL,
            UNIQUE(flag_id, environment)
        );

        CREATE TABLE IF NOT EXISTS flag_events (
            id         TEXT PRIMARY KEY,
            flag_id    TEXT NOT NULL,
            event_type TEXT NOT NULL,
            note       TEXT NOT NULL DEFAULT '',
            author     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_flag_status ON feature_flags (status);
        CREATE INDEX IF NOT EXISTS idx_flag_key    ON feature_flags (key);
        CREATE INDEX IF NOT EXISTS idx_flag_owner  ON feature_flags (owner);
        CREATE INDEX IF NOT EXISTS idx_fenv_flag   ON flag_environments (flag_id);
        CREATE INDEX IF NOT EXISTS idx_fevt_flag   ON flag_events (flag_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "flag"


def _unique_key(con: sqlite3.Connection, base: str, exclude_id: str = "") -> str:
    key, n = base, 1
    while True:
        row = con.execute("SELECT id FROM feature_flags WHERE key=?", (key,)).fetchone()
        if not row or row[0] == exclude_id:
            return key
        key = f"{base}_{n}"; n += 1


def _get_flag_or_404(con: sqlite3.Connection, flag_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_FLAG_COLS)} FROM feature_flags WHERE id=?",
        (flag_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Flag not found")
    return row


def _rollout_bucket(flag_key: str, environment: str, tenant_id: str) -> int:
    identity = tenant_id or "anonymous"
    digest = hashlib.sha256(f"{flag_key}:{environment}:{identity}".encode("utf-8")).hexdigest()
    return (int(digest, 16) % 100) + 1


def evaluate_feature_flag(flag_key: str, environment: str = "production", tenant_id: str = "") -> dict:
    key = _slugify(flag_key)
    try:
        con = _conn()
        flag = con.execute(
            f"SELECT {','.join(_FLAG_COLS)} FROM feature_flags WHERE key=?",
            (key,),
        ).fetchone()
        if not flag:
            con.close()
            raise HTTPException(404, "Flag not found")
        flag_d = dict(zip(_FLAG_COLS, flag))
        env = con.execute(
            f"SELECT {','.join(_ENV_COLS)} FROM flag_environments "
            "WHERE flag_id=? AND environment=?",
            (flag_d["id"], environment),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))

    bucket = _rollout_bucket(key, environment, tenant_id)
    result = {
        "key": key,
        "flag_id": flag_d["id"],
        "environment": environment,
        "tenant_id": tenant_id,
        "status": flag_d["status"],
        "enabled": False,
        "rollout_pct": 0.0,
        "bucket": bucket,
        "reason": "disabled",
    }
    if flag_d["status"] != "active":
        result["reason"] = "flag_not_active"
        return result
    if not env:
        result["reason"] = "environment_not_configured"
        return result
    env_d = dict(zip(_ENV_COLS, env))
    result["rollout_pct"] = float(env_d["rollout_pct"] or 0.0)
    if not bool(env_d["enabled"]):
        result["reason"] = "environment_disabled"
        return result
    result["enabled"] = result["rollout_pct"] >= 100 or bucket <= result["rollout_pct"]
    result["reason"] = "enabled" if result["enabled"] else "rollout_excluded"
    return result


def _log_event(con: sqlite3.Connection, flag_id: str,
               event_type: str, note: str, author: str, now: str) -> None:
    con.execute(
        f"INSERT INTO flag_events ({','.join(_EVT_COLS)}) "
        f"VALUES ({','.join(['?']*len(_EVT_COLS))})",
        (str(uuid.uuid4()), flag_id, event_type, note, author, now),
    )


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class FlagCreate(BaseModel):
    name:        str
    description: str = ""
    owner:       str = ""
    tags:        str = ""


class FlagPatch(BaseModel):
    name:        Optional[str] = None
    description: Optional[str] = None
    owner:       Optional[str] = None
    tags:        Optional[str] = None


class TransitionBody(BaseModel):
    status: str
    author: str = ""


class EnvUpsert(BaseModel):
    environment: str
    enabled:     bool  = False
    rollout_pct: float = 0.0
    notes:       str   = ""
    author:      str   = ""

    @field_validator("rollout_pct")
    @classmethod
    def pct_range(cls, v: float) -> float:
        if not 0 <= v <= 100:
            raise ValueError("rollout_pct must be between 0 and 100")
        return v


class EventCreate(BaseModel):
    event_type: str = "note"
    note:       str
    author:     str = ""


class EvaluateBatchBody(BaseModel):
    keys: List[str]
    environment: str = "production"
    tenant_id: str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("", summary="List feature flags")
async def list_flags(
    q:      Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(name LIKE ? OR key LIKE ? OR tags LIKE ? OR owner LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if status:
        where.append("status = ?"); params.append(status)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM feature_flags {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_FLAG_COLS)} FROM feature_flags {clause} "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "flags": [dict(zip(_FLAG_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("", status_code=201, summary="Create feature flag")
async def create_flag(body: FlagCreate, _auth=Depends(require_local_auth)):
    flag_id = str(uuid.uuid4())
    now     = _now()
    try:
        con = _conn()
        key = _unique_key(con, _slugify(body.name))
        con.execute(
            f"INSERT INTO feature_flags ({','.join(_FLAG_COLS)}) "
            f"VALUES ({','.join(['?']*len(_FLAG_COLS))})",
            (flag_id, body.name, key, body.description,
             "draft", body.owner, body.tags, now, now),
        )
        _log_event(con, flag_id, "created", "Flag created.", body.owner, now)
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": flag_id, "key": key, "status": "draft"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Feature flag statistics")
async def flag_stats(_auth=Depends(require_local_auth)):
    try:
        con    = _conn()
        total  = con.execute("SELECT COUNT(*) FROM feature_flags").fetchone()[0]
        active = con.execute(
            "SELECT COUNT(*) FROM feature_flags WHERE status='active'"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM feature_flags GROUP BY status"
        ).fetchall()
        enabled_envs = con.execute(
            "SELECT COUNT(*) FROM flag_environments WHERE enabled=1"
        ).fetchone()[0]
        total_envs = con.execute(
            "SELECT COUNT(*) FROM flag_environments"
        ).fetchone()[0]
        by_env = con.execute(
            "SELECT environment, SUM(enabled), COUNT(*) FROM flag_environments "
            "GROUP BY environment ORDER BY COUNT(*) DESC"
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":        total,
        "active":       active,
        "enabled_envs": enabled_envs,
        "total_envs":   total_envs,
        "by_status":    [{"status": s, "count": c} for s, c in by_status],
        "by_env":       [
            {"environment": e, "enabled": int(en or 0), "total": int(t)}
            for e, en, t in by_env
        ],
    }


# ── Single flag ───────────────────────────────────────────────────────────────

@router.post("/evaluate", summary="Evaluate multiple feature flags")
async def evaluate_flags(body: EvaluateBatchBody, _auth=Depends(require_local_auth)):
    decisions = {}
    for raw_key in body.keys[:100]:
        key = _slugify(raw_key)
        try:
            decisions[key] = evaluate_feature_flag(key, body.environment, body.tenant_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            decisions[key] = {
                "key": key,
                "environment": body.environment,
                "tenant_id": body.tenant_id,
                "enabled": False,
                "rollout_pct": 0.0,
                "bucket": _rollout_bucket(key, body.environment, body.tenant_id),
                "reason": "not_found",
            }
    return {
        "environment": body.environment,
        "tenant_id": body.tenant_id,
        "flags": decisions,
    }


@router.get("/evaluate/{flag_key}", summary="Evaluate a feature flag for an environment and tenant")
async def evaluate_flag(
    flag_key: str,
    environment: str = Query("production", min_length=1, max_length=80),
    tenant_id: str = Query("", max_length=160),
    _auth=Depends(require_local_auth),
):
    return evaluate_feature_flag(flag_key, environment, tenant_id)


@router.get("/{flag_id}", summary="Get feature flag")
async def get_flag(flag_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_flag_or_404(con, flag_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_FLAG_COLS, row))


@router.patch("/{flag_id}", summary="Update feature flag metadata")
async def patch_flag(
    flag_id: str, body: FlagPatch, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_flag_or_404(con, flag_id)
        sets, params = ["updated_at=?"], [_now()]
        if body.name is not None:
            new_key = _unique_key(con, _slugify(body.name), exclude_id=flag_id)
            sets += ["name=?", "key=?"]
            params += [body.name, new_key]
        for field in ("description", "owner", "tags"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(flag_id)
        con.execute(f"UPDATE feature_flags SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_FLAG_COLS)} FROM feature_flags WHERE id=?",
            (flag_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_FLAG_COLS, row))


@router.delete("/{flag_id}", status_code=204, summary="Delete feature flag")
async def delete_flag(flag_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_flag_or_404(con, flag_id)
        con.execute("DELETE FROM flag_environments WHERE flag_id=?", (flag_id,))
        con.execute("DELETE FROM flag_events WHERE flag_id=?", (flag_id,))
        con.execute("DELETE FROM feature_flags WHERE id=?", (flag_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/{flag_id}/transition", summary="Transition flag status")
async def transition_flag(
    flag_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_flag_or_404(con, flag_id)
        d   = dict(zip(_FLAG_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        now = _now()
        con.execute(
            "UPDATE feature_flags SET status=?, updated_at=? WHERE id=?",
            (body.status, now, flag_id),
        )
        _log_event(con, flag_id, "status_changed",
                   f"Status changed to {body.status}.", body.author, now)
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Environments ──────────────────────────────────────────────────────────────

@router.get("/{flag_id}/environments", summary="List per-environment flag state")
async def list_environments(flag_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_flag_or_404(con, flag_id)
        rows = con.execute(
            f"SELECT {','.join(_ENV_COLS)} FROM flag_environments "
            "WHERE flag_id=? ORDER BY environment ASC LIMIT 100",
            (flag_id,),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"environments": [dict(zip(_ENV_COLS, r)) for r in rows]}


@router.post("/{flag_id}/environments", summary="Upsert per-environment flag state")
async def upsert_environment(
    flag_id: str, body: EnvUpsert, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_flag_or_404(con, flag_id)
        now     = _now()
        existing = con.execute(
            "SELECT id, enabled FROM flag_environments WHERE flag_id=? AND environment=?",
            (flag_id, body.environment),
        ).fetchone()
        if existing:
            env_id   = existing[0]
            was_enabled = bool(existing[1])
            con.execute(
                "UPDATE flag_environments "
                "SET enabled=?, rollout_pct=?, notes=?, updated_at=? "
                "WHERE id=?",
                (1 if body.enabled else 0, body.rollout_pct, body.notes, now, env_id),
            )
            if body.enabled != was_enabled:
                evt = "enabled" if body.enabled else "disabled"
                _log_event(con, flag_id, evt,
                           f"Flag {evt} in {body.environment}.", body.author, now)
            else:
                _log_event(con, flag_id, "rollout_changed",
                           f"Rollout in {body.environment} → {body.rollout_pct}%.",
                           body.author, now)
            created = False
        else:
            env_id = str(uuid.uuid4())
            con.execute(
                f"INSERT INTO flag_environments ({','.join(_ENV_COLS)}) "
                f"VALUES ({','.join(['?']*len(_ENV_COLS))})",
                (env_id, flag_id, body.environment,
                 1 if body.enabled else 0, body.rollout_pct, body.notes, now),
            )
            evt = "enabled" if body.enabled else "disabled"
            _log_event(con, flag_id, evt,
                       f"Flag configured in {body.environment} ({evt}).",
                       body.author, now)
            created = True
        con.execute(
            "UPDATE feature_flags SET updated_at=? WHERE id=?", (now, flag_id)
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    status_code = 201 if created else 200
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"id": env_id, "ok": True, "created": created},
        status_code=status_code,
    )


# ── Events ────────────────────────────────────────────────────────────────────

@router.get("/{flag_id}/events", summary="List flag events")
async def list_events(
    flag_id: str,
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_flag_or_404(con, flag_id)
        total = con.execute(
            "SELECT COUNT(*) FROM flag_events WHERE flag_id=?", (flag_id,)
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_EVT_COLS)} FROM flag_events "
            "WHERE flag_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (flag_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"events": [dict(zip(_EVT_COLS, r)) for r in rows], "total": total}


@router.post("/{flag_id}/events", status_code=201, summary="Add flag event")
async def add_event(
    flag_id: str, body: EventCreate, _auth=Depends(require_local_auth)
):
    if body.event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(
            400, f"Invalid event_type '{body.event_type}'. Valid: {sorted(_VALID_EVENT_TYPES)}"
        )
    try:
        con = _conn()
        _get_flag_or_404(con, flag_id)
        evt_id = str(uuid.uuid4())
        now    = _now()
        _log_event(con, flag_id, body.event_type, body.note, body.author, now)
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}
