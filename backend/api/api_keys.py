"""
API Key Manager
===============
Create and manage named API keys for external integrations.

Key format:   ak_{48 random hex chars}  (51 chars total)
Storage:      SHA-256 hash of the full key — the plaintext is shown ONCE on
              creation and never stored.
Display:      key_prefix = "ak_" + first 8 hex chars + "..."

Scopes (comma-separated, '' = full access):
  read, write, admin, webhooks, reports

Public helper:
  verify_api_key(key) → dict | None
    — looks up by hash, checks enabled + expiry, bumps last_used_at / use_count

Endpoints:
  GET    /api-keys
  POST   /api-keys            (201) — returns {"key": "<full plaintext>", ...}
  GET    /api-keys/stats
  GET    /api-keys/{key_id}
  PATCH  /api-keys/{key_id}
  DELETE /api-keys/{key_id}
  POST   /api-keys/{key_id}/rotate  — new key same settings, returns new plaintext
"""
from __future__ import annotations

import hashlib
import logging
import secrets
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
router = APIRouter(prefix="/api-keys", tags=["api_keys"])

_DB_PATH = str(Path(DATA_DIR) / "api_keys.db")

_KEY_COLS = [
    "id", "name", "key_prefix", "key_hash", "description",
    "scopes", "created_by", "created_at", "last_used_at",
    "expires_at", "enabled", "use_count",
]

_VALID_SCOPES = {"read", "write", "admin", "webhooks", "reports"}


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS api_keys (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            key_prefix   TEXT NOT NULL,
            key_hash     TEXT NOT NULL UNIQUE,
            description  TEXT NOT NULL DEFAULT '',
            scopes       TEXT NOT NULL DEFAULT '',
            created_by   TEXT NOT NULL DEFAULT 'admin',
            created_at   TEXT NOT NULL,
            last_used_at TEXT,
            expires_at   TEXT,
            enabled      INTEGER NOT NULL DEFAULT 1,
            use_count    INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_ak_hash
            ON api_keys (key_hash);
        CREATE INDEX IF NOT EXISTS idx_ak_enabled
            ON api_keys (enabled, expires_at);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Key helpers ───────────────────────────────────────────────────────────────

def _generate_key() -> tuple[str, str, str]:
    """Returns (full_key, key_prefix, key_hash)."""
    raw     = secrets.token_hex(24)          # 48 hex chars
    full    = f"ak_{raw}"                    # 51 chars
    prefix  = f"ak_{raw[:8]}..."             # display
    digest  = hashlib.sha256(full.encode()).hexdigest()
    return full, prefix, digest


def _hash_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


# ── Public helper ─────────────────────────────────────────────────────────────

def verify_api_key(key: str) -> Optional[dict]:
    """
    Validate a plaintext API key. Returns the key record dict (without
    key_hash) if valid, None if invalid/expired/disabled.
    Side-effects: bumps last_used_at and use_count on success.
    """
    if not key or not key.startswith("ak_"):
        return None
    digest = _hash_key(key)
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_KEY_COLS)} FROM api_keys WHERE key_hash=?", (digest,)
        ).fetchone()
        con.close()
    except Exception:
        return None
    if not row:
        return None
    record = dict(zip(_KEY_COLS, row))
    if not record["enabled"]:
        return None
    if record["expires_at"]:
        try:
            exp = datetime.fromisoformat(record["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return None
        except Exception:
            logger.warning("api_keys: malformed expires_at for key %s — treating as expired", record["id"])
            return None
    try:
        con = _conn()
        con.execute(
            "UPDATE api_keys SET last_used_at=?, use_count=use_count+1 WHERE id=?",
            (_now(), record["id"]),
        )
        con.commit()
        con.close()
    except Exception:
        pass
    record.pop("key_hash", None)
    return record


# ── Validation helpers ────────────────────────────────────────────────────────

def _parse_scopes(scopes_str: str) -> list[str]:
    return [s.strip() for s in scopes_str.split(",") if s.strip()]


def _validate_scopes(scopes: list[str]) -> None:
    invalid = set(scopes) - _VALID_SCOPES
    if invalid:
        raise HTTPException(400, f"Invalid scopes: {', '.join(sorted(invalid))}. "
                                 f"Valid: {', '.join(sorted(_VALID_SCOPES))}")


def _validate_expires_at(expires_at: Optional[str]) -> None:
    if expires_at is None:
        return
    try:
        dt = datetime.fromisoformat(expires_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt <= datetime.now(timezone.utc):
            raise HTTPException(400, "expires_at must be in the future")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "expires_at must be a valid ISO 8601 timestamp")


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class KeyCreate(BaseModel):
    name:        str
    description: str        = ""
    scopes:      list[str]  = []
    created_by:  str        = "admin"
    expires_at:  Optional[str] = None
    enabled:     bool       = True


class KeyPatch(BaseModel):
    name:        Optional[str]       = None
    description: Optional[str]       = None
    scopes:      Optional[list[str]] = None
    expires_at:  Optional[str]       = None
    enabled:     Optional[bool]      = None


# ── Sub-routes before /{key_id} ───────────────────────────────────────────────

@router.get("", summary="List API keys (hashes omitted)")
async def list_keys(
    enabled_only: bool = Query(False),
    limit:  int = Query(100, ge=1, le=1000),
    offset: int = Query(0,   ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if enabled_only:
        where.append("enabled = 1")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM api_keys {clause}", params
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_KEY_COLS)} FROM api_keys {clause} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    keys = []
    for row in rows:
        k = dict(zip(_KEY_COLS, row))
        k.pop("key_hash")
        keys.append(k)
    return {"keys": keys, "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201, summary="Create API key — full key returned once")
async def create_key(body: KeyCreate, _auth=Depends(require_local_auth)):
    if body.scopes:
        _validate_scopes(body.scopes)
    _validate_expires_at(body.expires_at)
    full_key, prefix, digest = _generate_key()
    key_id = str(uuid.uuid4())
    now    = _now()
    scopes_str = ",".join(body.scopes)
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO api_keys ({','.join(_KEY_COLS)}) "
            f"VALUES ({','.join(['?']*len(_KEY_COLS))})",
            (key_id, body.name, prefix, digest, body.description,
             scopes_str, body.created_by, now, None,
             body.expires_at, 1 if body.enabled else 0, 0),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    try:
        from backend.api.audit_log import write_audit_entry
        write_audit_entry(
            event_type="api_key.created", actor=body.created_by,
            action="create", outcome="ok", severity="info",
            summary=f"API key '{body.name}' created",
            resource_type="api_key", resource_id=key_id,
        )
    except Exception:
        pass
    return {
        "id":      key_id,
        "name":    body.name,
        "key":     full_key,
        "prefix":  prefix,
        "warning": "Store this key securely — it will not be shown again.",
    }


@router.get("/stats", summary="API key usage statistics")
async def key_stats(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        total   = con.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        enabled = con.execute("SELECT COUNT(*) FROM api_keys WHERE enabled=1").fetchone()[0]
        expired = con.execute(
            "SELECT COUNT(*) FROM api_keys "
            "WHERE expires_at IS NOT NULL AND expires_at < ?", (_now(),)
        ).fetchone()[0]
        never_used = con.execute(
            "SELECT COUNT(*) FROM api_keys WHERE use_count=0"
        ).fetchone()[0]
        total_calls = con.execute("SELECT COALESCE(SUM(use_count),0) FROM api_keys").fetchone()[0]
        top = con.execute(
            "SELECT name, key_prefix, use_count FROM api_keys "
            "ORDER BY use_count DESC LIMIT 5"
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":       total,
        "enabled":     enabled,
        "disabled":    total - enabled,
        "expired":     expired,
        "never_used":  never_used,
        "total_calls": total_calls,
        "top_keys":    [{"name": r[0], "prefix": r[1], "use_count": r[2]} for r in top],
    }


# ── Key-specific routes ───────────────────────────────────────────────────────

@router.get("/{key_id}", summary="Get API key detail")
async def get_key(key_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_KEY_COLS)} FROM api_keys WHERE id=?", (key_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not row:
        raise HTTPException(404, "API key not found")
    k = dict(zip(_KEY_COLS, row))
    k.pop("key_hash")
    k["scopes"] = _parse_scopes(k.get("scopes", ""))
    return k


@router.patch("/{key_id}", summary="Update API key")
async def patch_key(key_id: str, body: KeyPatch, _auth=Depends(require_local_auth)):
    updates, params = [], []
    if body.name is not None:
        updates.append("name = ?"); params.append(body.name)
    if body.description is not None:
        updates.append("description = ?"); params.append(body.description)
    if body.scopes is not None:
        _validate_scopes(body.scopes)
        updates.append("scopes = ?"); params.append(",".join(body.scopes))
    if body.expires_at is not None:
        _validate_expires_at(body.expires_at)
        updates.append("expires_at = ?"); params.append(body.expires_at)
    if body.enabled is not None:
        updates.append("enabled = ?"); params.append(1 if body.enabled else 0)
    if not updates:
        raise HTTPException(400, "No fields to update")
    params.append(key_id)
    try:
        con = _conn()
        con.execute(f"UPDATE api_keys SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "API key not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


@router.delete("/{key_id}", status_code=204, summary="Delete API key")
async def delete_key(key_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/{key_id}/rotate", status_code=201,
             summary="Rotate API key — invalidates old key, returns new plaintext")
async def rotate_key(key_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_KEY_COLS)} FROM api_keys WHERE id=?", (key_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not row:
        raise HTTPException(404, "API key not found")
    old = dict(zip(_KEY_COLS, row))
    full_key, prefix, digest = _generate_key()
    now = _now()
    try:
        con = _conn()
        con.execute(
            "UPDATE api_keys SET key_prefix=?, key_hash=?, use_count=0, "
            "last_used_at=NULL, enabled=1 WHERE id=?",
            (prefix, digest, key_id),
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    try:
        from backend.api.audit_log import write_audit_entry
        write_audit_entry(
            event_type="api_key.rotated", actor="admin",
            action="rotate", outcome="ok", severity="info",
            summary=f"API key '{old['name']}' rotated",
            resource_type="api_key", resource_id=key_id,
        )
    except Exception:
        pass
    return {
        "id":      key_id,
        "name":    old["name"],
        "key":     full_key,
        "prefix":  prefix,
        "warning": "Store this key securely — it will not be shown again.",
    }
