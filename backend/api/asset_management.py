"""
Asset Management / CMDB
========================
Configuration Item (CI) registry with 5-state lifecycle, directed
relationships between assets, and an immutable event log.

Tables:
  assets              — CI records
  asset_relationships — directed edges between CIs (UNIQUE constraint)
  asset_events        — append-only audit log

State machine:
  discovered  → active | retired
  active      → maintenance | deprecated | retired
  maintenance → active | retired
  deprecated  → retired
  retired     → (terminal)

Asset types: server, application, database, network_device,
             storage, container, service, other

Relationship types: depends_on, hosts, connects_to, is_part_of,
                    monitors, backs_up, replicates_to

Endpoints:
  GET    /assets
  POST   /assets                                      (201)
  GET    /assets/stats
  GET    /assets/{asset_id}
  PATCH  /assets/{asset_id}
  DELETE /assets/{asset_id}                           (204)
  POST   /assets/{asset_id}/transition
  GET    /assets/{asset_id}/relationships
  POST   /assets/{asset_id}/relationships             (201)
  DELETE /assets/{asset_id}/relationships/{rel_id}    (204)
  GET    /assets/{asset_id}/events
  POST   /assets/{asset_id}/events                    (201)
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
router = APIRouter(prefix="/assets", tags=["assets"])

_DB_PATH = str(Path(DATA_DIR) / "asset_management.db")

_ASSET_COLS = [
    "id", "name", "type", "status", "environment",
    "owner", "team", "ip_address", "hostname", "version",
    "description", "tags", "linked_service_id",
    "created_at", "updated_at",
]
_REL_COLS = ["id", "source_id", "target_id", "relation_type", "created_at"]
_EVT_COLS = ["id", "asset_id", "event_type", "note", "author", "created_at"]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "discovered":  {"active", "retired"},
    "active":      {"maintenance", "deprecated", "retired"},
    "maintenance": {"active", "retired"},
    "deprecated":  {"retired"},
    "retired":     set(),
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())

_VALID_TYPES = {
    "server", "application", "database", "network_device",
    "storage", "container", "service", "other",
}

_VALID_RELATION_TYPES = {
    "depends_on", "hosts", "connects_to", "is_part_of",
    "monitors", "backs_up", "replicates_to",
}

_VALID_EVENT_TYPES = {
    "note", "status_change", "config_update", "incident_linked",
    "change_linked", "relationship_added", "relationship_removed",
}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS assets (
            id                TEXT PRIMARY KEY,
            name              TEXT NOT NULL,
            type              TEXT NOT NULL DEFAULT 'other',
            status            TEXT NOT NULL DEFAULT 'discovered',
            environment       TEXT NOT NULL DEFAULT '',
            owner             TEXT NOT NULL DEFAULT '',
            team              TEXT NOT NULL DEFAULT '',
            ip_address        TEXT NOT NULL DEFAULT '',
            hostname          TEXT NOT NULL DEFAULT '',
            version           TEXT NOT NULL DEFAULT '',
            description       TEXT NOT NULL DEFAULT '',
            tags              TEXT NOT NULL DEFAULT '',
            linked_service_id TEXT,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS asset_relationships (
            id            TEXT PRIMARY KEY,
            source_id     TEXT NOT NULL,
            target_id     TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            UNIQUE(source_id, target_id, relation_type)
        );

        CREATE TABLE IF NOT EXISTS asset_events (
            id         TEXT PRIMARY KEY,
            asset_id   TEXT NOT NULL,
            event_type TEXT NOT NULL,
            note       TEXT NOT NULL DEFAULT '',
            author     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_asset_status   ON assets (status);
        CREATE INDEX IF NOT EXISTS idx_asset_type     ON assets (type);
        CREATE INDEX IF NOT EXISTS idx_asset_env      ON assets (environment);
        CREATE INDEX IF NOT EXISTS idx_asset_owner    ON assets (owner);
        CREATE INDEX IF NOT EXISTS idx_asset_team     ON assets (team);
        CREATE INDEX IF NOT EXISTS idx_asset_hostname ON assets (hostname);
        CREATE INDEX IF NOT EXISTS idx_rel_source     ON asset_relationships (source_id);
        CREATE INDEX IF NOT EXISTS idx_rel_target     ON asset_relationships (target_id);
        CREATE INDEX IF NOT EXISTS idx_evt_asset      ON asset_events (asset_id, created_at DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_asset_or_404(con: sqlite3.Connection, asset_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_ASSET_COLS)} FROM assets WHERE id=?",
        (asset_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Asset not found")
    return row


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    name:              str
    type:              str           = "other"
    environment:       str           = ""
    owner:             str           = ""
    team:              str           = ""
    ip_address:        str           = ""
    hostname:          str           = ""
    version:           str           = ""
    description:       str           = ""
    tags:              str           = ""
    linked_service_id: Optional[str] = None


class AssetPatch(BaseModel):
    name:              Optional[str] = None
    type:              Optional[str] = None
    environment:       Optional[str] = None
    owner:             Optional[str] = None
    team:              Optional[str] = None
    ip_address:        Optional[str] = None
    hostname:          Optional[str] = None
    version:           Optional[str] = None
    description:       Optional[str] = None
    tags:              Optional[str] = None
    linked_service_id: Optional[str] = None


class TransitionBody(BaseModel):
    status: str
    note:   str = ""
    author: str = ""


class RelationshipCreate(BaseModel):
    target_id:     str
    relation_type: str


class EventCreate(BaseModel):
    event_type: str = "note"
    note:       str
    author:     str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("", summary="List assets")
async def list_assets(
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
        where.append("(name LIKE ? OR hostname LIKE ? OR ip_address LIKE ? OR tags LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if type:
        where.append("type = ?"); params.append(type)
    if status:
        where.append("status = ?"); params.append(status)
    if environment:
        where.append("environment = ?"); params.append(environment)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con   = _conn()
        total = con.execute(f"SELECT COUNT(*) FROM assets {clause}", params).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_ASSET_COLS)} FROM assets {clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "assets": [dict(zip(_ASSET_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("", status_code=201, summary="Create asset")
async def create_asset(body: AssetCreate, _auth=Depends(require_local_auth)):
    if body.type not in _VALID_TYPES:
        raise HTTPException(400, f"Invalid type '{body.type}'. Valid: {sorted(_VALID_TYPES)}")
    asset_id = str(uuid.uuid4())
    now      = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO assets ({','.join(_ASSET_COLS)}) "
            f"VALUES ({','.join(['?']*len(_ASSET_COLS))})",
            (asset_id, body.name, body.type, "discovered", body.environment,
             body.owner, body.team, body.ip_address, body.hostname, body.version,
             body.description, body.tags, body.linked_service_id, now, now),
        )
        con.execute(
            f"INSERT INTO asset_events ({','.join(_EVT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_EVT_COLS))})",
            (str(uuid.uuid4()), asset_id, "note", "Asset registered.", body.owner or "system", now),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": asset_id, "name": body.name, "status": "discovered"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", summary="Asset statistics")
async def asset_stats(_auth=Depends(require_local_auth)):
    try:
        con      = _conn()
        total    = con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        active   = con.execute("SELECT COUNT(*) FROM assets WHERE status='active'").fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM assets GROUP BY status"
        ).fetchall()
        by_type  = con.execute(
            "SELECT type, COUNT(*) FROM assets GROUP BY type ORDER BY COUNT(*) DESC"
        ).fetchall()
        by_env   = con.execute(
            "SELECT environment, COUNT(*) FROM assets WHERE environment != '' "
            "GROUP BY environment ORDER BY COUNT(*) DESC"
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":     total,
        "active":    active,
        "by_status": [{"status": s, "count": c} for s, c in by_status],
        "by_type":   [{"type": t, "count": c} for t, c in by_type],
        "by_env":    [{"environment": e, "count": c} for e, c in by_env],
    }


# ── Single asset ──────────────────────────────────────────────────────────────

@router.get("/{asset_id}", summary="Get asset")
async def get_asset(asset_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = _get_asset_or_404(con, asset_id)
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_ASSET_COLS, row))


@router.patch("/{asset_id}", summary="Update asset metadata")
async def patch_asset(
    asset_id: str, body: AssetPatch, _auth=Depends(require_local_auth)
):
    if body.type is not None and body.type not in _VALID_TYPES:
        raise HTTPException(400, f"Invalid type '{body.type}'. Valid: {sorted(_VALID_TYPES)}")
    try:
        con = _conn()
        _get_asset_or_404(con, asset_id)
        sets, params = ["updated_at=?"], [_now()]
        for field in ("name", "type", "environment", "owner", "team",
                      "ip_address", "hostname", "version", "description",
                      "tags", "linked_service_id"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        params.append(asset_id)
        con.execute(f"UPDATE assets SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_ASSET_COLS)} FROM assets WHERE id=?",
            (asset_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return dict(zip(_ASSET_COLS, row))


@router.delete("/{asset_id}", status_code=204, summary="Delete asset")
async def delete_asset(asset_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_asset_or_404(con, asset_id)
        con.execute(
            "DELETE FROM asset_relationships WHERE source_id=? OR target_id=?",
            (asset_id, asset_id),
        )
        con.execute("DELETE FROM asset_events WHERE asset_id=?", (asset_id,))
        con.execute("DELETE FROM assets WHERE id=?", (asset_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/{asset_id}/transition", summary="Transition asset status")
async def transition_asset(
    asset_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}")
    try:
        con = _conn()
        row = _get_asset_or_404(con, asset_id)
        d   = dict(zip(_ASSET_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        now = _now()
        con.execute(
            "UPDATE assets SET status=?, updated_at=? WHERE id=?",
            (body.status, now, asset_id),
        )
        note_text = body.note or f"Status changed to {body.status}."
        con.execute(
            f"INSERT INTO asset_events ({','.join(_EVT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_EVT_COLS))})",
            (str(uuid.uuid4()), asset_id, "status_change", note_text, body.author, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True, "status": body.status}


# ── Relationships ─────────────────────────────────────────────────────────────

@router.get("/{asset_id}/relationships", summary="List asset relationships")
async def list_relationships(asset_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_asset_or_404(con, asset_id)
        rows = con.execute(
            f"SELECT {','.join(_REL_COLS)} FROM asset_relationships "
            "WHERE source_id=? OR target_id=? ORDER BY created_at DESC LIMIT 200",
            (asset_id, asset_id),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"relationships": [dict(zip(_REL_COLS, r)) for r in rows]}


@router.post("/{asset_id}/relationships", status_code=201,
             summary="Add asset relationship")
async def add_relationship(
    asset_id: str, body: RelationshipCreate, _auth=Depends(require_local_auth)
):
    if body.relation_type not in _VALID_RELATION_TYPES:
        raise HTTPException(
            400, f"Invalid relation_type '{body.relation_type}'. Valid: {sorted(_VALID_RELATION_TYPES)}"
        )
    try:
        con = _conn()
        _get_asset_or_404(con, asset_id)
        if not con.execute("SELECT 1 FROM assets WHERE id=?", (body.target_id,)).fetchone():
            raise HTTPException(404, "Target asset not found")
        rel_id = str(uuid.uuid4())
        now    = _now()
        try:
            con.execute(
                f"INSERT INTO asset_relationships ({','.join(_REL_COLS)}) "
                f"VALUES ({','.join(['?']*len(_REL_COLS))})",
                (rel_id, asset_id, body.target_id, body.relation_type, now),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Relationship already exists")
        con.execute(
            f"INSERT INTO asset_events ({','.join(_EVT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_EVT_COLS))})",
            (str(uuid.uuid4()), asset_id, "relationship_added",
             f"Added {body.relation_type} → {body.target_id}", "", now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": rel_id, "ok": True}


@router.delete("/{asset_id}/relationships/{rel_id}", status_code=204,
               summary="Remove asset relationship")
async def delete_relationship(
    asset_id: str, rel_id: str, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        _get_asset_or_404(con, asset_id)
        row = con.execute(
            "SELECT id FROM asset_relationships "
            "WHERE id=? AND (source_id=? OR target_id=?)",
            (rel_id, asset_id, asset_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Relationship not found")
        now = _now()
        con.execute("DELETE FROM asset_relationships WHERE id=?", (rel_id,))
        con.execute(
            f"INSERT INTO asset_events ({','.join(_EVT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_EVT_COLS))})",
            (str(uuid.uuid4()), asset_id, "relationship_removed",
             f"Removed relationship {rel_id}", "", now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))


# ── Events ────────────────────────────────────────────────────────────────────

@router.get("/{asset_id}/events", summary="List asset events")
async def list_events(
    asset_id: str,
    limit:  int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_asset_or_404(con, asset_id)
        total = con.execute(
            "SELECT COUNT(*) FROM asset_events WHERE asset_id=?",
            (asset_id,),
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_EVT_COLS)} FROM asset_events "
            "WHERE asset_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (asset_id, limit, offset),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"events": [dict(zip(_EVT_COLS, r)) for r in rows], "total": total}


@router.post("/{asset_id}/events", status_code=201, summary="Add asset event")
async def add_event(
    asset_id: str, body: EventCreate, _auth=Depends(require_local_auth)
):
    if body.event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(
            400, f"Invalid event_type '{body.event_type}'. Valid: {sorted(_VALID_EVENT_TYPES)}"
        )
    try:
        con = _conn()
        _get_asset_or_404(con, asset_id)
        evt_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO asset_events ({','.join(_EVT_COLS)}) "
            f"VALUES ({','.join(['?']*len(_EVT_COLS))})",
            (evt_id, asset_id, body.event_type, body.note, body.author, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": evt_id, "ok": True}
