"""
Runbooks
========
Human-readable incident response and operational documentation.
Each runbook stores Markdown content and keeps a full version history —
every PATCH that changes content_md creates an immutable snapshot.

Tables:
  runbooks          — documents (title, slug, category, tags, markdown body)
  runbook_versions  — immutable snapshots (version_number per runbook,
                      content_md, editor, change_note)

Key behaviours:
  - slug is auto-derived from title (lowercase, hyphens) if not supplied
  - view_count is incremented on every GET /{id} request
  - Full-text search across title, tags, category, and content preview
  - linked_playbook_id is an optional FK to playbooks (advisory only)

Endpoints:
  GET    /runbooks
  POST   /runbooks                          (201)
  GET    /runbooks/stats
  GET    /runbooks/categories
  GET    /runbooks/{runbook_id}             — bumps view_count
  PATCH  /runbooks/{runbook_id}             — creates version snapshot if content changed
  DELETE /runbooks/{runbook_id}
  GET    /runbooks/{runbook_id}/versions
  GET    /runbooks/{runbook_id}/versions/{version_number}
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
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runbooks", tags=["runbooks"])

_DB_PATH = str(Path(DATA_DIR) / "runbooks.db")

_RB_COLS = [
    "id", "title", "slug", "category", "tags", "content_md",
    "owner", "linked_playbook_id", "created_at", "updated_at", "view_count",
]
_VER_COLS = [
    "id", "runbook_id", "version_number", "content_md",
    "edited_by", "edited_at", "change_note",
]


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS runbooks (
            id                 TEXT PRIMARY KEY,
            title              TEXT NOT NULL,
            slug               TEXT NOT NULL UNIQUE,
            category           TEXT NOT NULL DEFAULT '',
            tags               TEXT NOT NULL DEFAULT '',
            content_md         TEXT NOT NULL DEFAULT '',
            owner              TEXT NOT NULL DEFAULT '',
            linked_playbook_id TEXT,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            view_count         INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS runbook_versions (
            id             TEXT PRIMARY KEY,
            runbook_id     TEXT NOT NULL,
            version_number INTEGER NOT NULL,
            content_md     TEXT NOT NULL DEFAULT '',
            edited_by      TEXT NOT NULL DEFAULT '',
            edited_at      TEXT NOT NULL,
            change_note    TEXT NOT NULL DEFAULT '',
            UNIQUE (runbook_id, version_number)
        );

        CREATE INDEX IF NOT EXISTS idx_rb_slug
            ON runbooks (slug);
        CREATE INDEX IF NOT EXISTS idx_rb_category
            ON runbooks (category);
        CREATE INDEX IF NOT EXISTS idx_rb_updated
            ON runbooks (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_rv_runbook
            ON runbook_versions (runbook_id, version_number DESC);
    """)
    con.commit()
    con.close()


_init_db()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Slug helpers ──────────────────────────────────────────────────────────────

def _slugify(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "runbook"


def _unique_slug(base: str, exclude_id: Optional[str] = None) -> str:
    slug, n = base, 0
    while True:
        con = _conn()
        row = con.execute(
            "SELECT id FROM runbooks WHERE slug=?", (slug,)
        ).fetchone()
        con.close()
        if not row or (exclude_id and row[0] == exclude_id):
            return slug
        n += 1
        slug = f"{base}-{n}"


# ── Version helpers ───────────────────────────────────────────────────────────

def _next_version_number(runbook_id: str) -> int:
    try:
        con = _conn()
        row = con.execute(
            "SELECT COALESCE(MAX(version_number), 0) FROM runbook_versions WHERE runbook_id=?",
            (runbook_id,),
        ).fetchone()
        con.close()
        return (row[0] or 0) + 1
    except Exception:
        return 1


def _save_version(runbook_id: str, content_md: str,
                  edited_by: str, change_note: str) -> int:
    ver_num = _next_version_number(runbook_id)
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO runbook_versions ({','.join(_VER_COLS)}) "
            f"VALUES ({','.join(['?']*len(_VER_COLS))})",
            (str(uuid.uuid4()), runbook_id, ver_num,
             content_md, edited_by, _now(), change_note),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.warning("Runbooks: version save failed: %s", exc)
    return ver_num


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RunbookCreate(BaseModel):
    title:              str
    slug:               Optional[str] = None
    category:           str           = ""
    tags:               str           = ""
    content_md:         str           = ""
    owner:              str           = ""
    linked_playbook_id: Optional[str] = None


class RunbookPatch(BaseModel):
    title:              Optional[str]  = None
    slug:               Optional[str]  = None
    category:           Optional[str]  = None
    tags:               Optional[str]  = None
    content_md:         Optional[str]  = None
    owner:              Optional[str]  = None
    linked_playbook_id: Optional[str]  = None
    edited_by:          str            = ""
    change_note:        str            = ""


# ── Sub-routes before /{runbook_id} ───────────────────────────────────────────

@router.get("", summary="List runbooks with search and filters")
async def list_runbooks(
    q:        Optional[str] = Query(None, description="Search title, tags, category"),
    category: Optional[str] = Query(None),
    tag:      Optional[str] = Query(None),
    limit:    int = Query(50,  ge=1, le=500),
    offset:   int = Query(0,   ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(title LIKE ? OR tags LIKE ? OR category LIKE ? OR content_md LIKE ?)")
        pct = f"%{q}%"
        params += [pct, pct, pct, pct]
    if category:
        where.append("category = ?"); params.append(category)
    if tag:
        where.append("tags LIKE ?"); params.append(f"%{tag}%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        con = _conn()
        total = con.execute(
            f"SELECT COUNT(*) FROM runbooks {clause}", params
        ).fetchone()[0]
        rows = con.execute(
            f"SELECT {','.join(_RB_COLS)} FROM runbooks {clause} "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    results = []
    for row in rows:
        rb = dict(zip(_RB_COLS, row))
        # Return a truncated preview instead of full markdown in list view
        rb["content_preview"] = rb["content_md"][:200].rstrip()
        rb.pop("content_md")
        rb["tags"] = [t.strip() for t in rb["tags"].split(",") if t.strip()]
        results.append(rb)
    return {"runbooks": results, "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201, summary="Create runbook")
async def create_runbook(body: RunbookCreate, _auth=Depends(require_local_auth)):
    base = _slugify(body.slug or body.title)
    slug = _unique_slug(base)
    rb_id = str(uuid.uuid4())
    now   = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO runbooks ({','.join(_RB_COLS)}) "
            f"VALUES ({','.join(['?']*len(_RB_COLS))})",
            (rb_id, body.title, slug, body.category, body.tags,
             body.content_md, body.owner, body.linked_playbook_id,
             now, now, 0),
        )
        con.commit()
        con.close()
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"Slug '{slug}' already exists")
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if body.content_md:
        _save_version(rb_id, body.content_md, body.owner or "system", "Initial version")
    return {"id": rb_id, "title": body.title, "slug": slug}


@router.get("/stats", summary="Runbook statistics")
async def runbook_stats(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        total    = con.execute("SELECT COUNT(*) FROM runbooks").fetchone()[0]
        versions = con.execute("SELECT COUNT(*) FROM runbook_versions").fetchone()[0]
        cats     = con.execute(
            "SELECT category, COUNT(*) as n FROM runbooks "
            "WHERE category != '' GROUP BY category ORDER BY n DESC LIMIT 10"
        ).fetchall()
        top_viewed = con.execute(
            "SELECT title, slug, view_count FROM runbooks "
            "ORDER BY view_count DESC LIMIT 5"
        ).fetchall()
        most_edited = con.execute(
            "SELECT r.title, r.slug, COUNT(v.id) as edits "
            "FROM runbooks r JOIN runbook_versions v ON v.runbook_id = r.id "
            "GROUP BY r.id ORDER BY edits DESC LIMIT 5"
        ).fetchall()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {
        "total":        total,
        "total_versions": versions,
        "by_category":  [{"category": r[0], "count": r[1]} for r in cats],
        "top_viewed":   [{"title": r[0], "slug": r[1], "views": r[2]} for r in top_viewed],
        "most_edited":  [{"title": r[0], "slug": r[1], "edits": r[2]} for r in most_edited],
    }


@router.get("/categories", summary="Distinct categories in use")
async def list_categories(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        rows = con.execute(
            "SELECT DISTINCT category FROM runbooks "
            "WHERE category != '' ORDER BY category LIMIT 100"
        ).fetchall()
        con.close()
    except Exception:
        return {"categories": []}
    return {"categories": [r[0] for r in rows]}


# ── Runbook-specific routes ───────────────────────────────────────────────────

@router.get("/{runbook_id}", summary="Runbook detail — increments view_count")
async def get_runbook(runbook_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_RB_COLS)} FROM runbooks WHERE id=? OR slug=?",
            (runbook_id, runbook_id),
        ).fetchone()
        if not row:
            con.close()
            raise HTTPException(404, "Runbook not found")
        con.execute(
            "UPDATE runbooks SET view_count=view_count+1 WHERE id=?", (row[0],)
        )
        con.commit()
        # latest version metadata
        ver_row = con.execute(
            "SELECT version_number, edited_by, edited_at, change_note "
            "FROM runbook_versions WHERE runbook_id=? ORDER BY version_number DESC LIMIT 1",
            (row[0],),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    rb = dict(zip(_RB_COLS, row))
    rb["tags"] = [t.strip() for t in rb["tags"].split(",") if t.strip()]
    rb["latest_version"] = {
        "version_number": ver_row[0], "edited_by":  ver_row[1],
        "edited_at":      ver_row[2], "change_note": ver_row[3],
    } if ver_row else None
    return rb


@router.patch("/{runbook_id}", summary="Update runbook — saves version snapshot if content changes")
async def patch_runbook(
    runbook_id: str, body: RunbookPatch, _auth=Depends(require_local_auth)
):
    updates, params = [], []
    if body.title is not None:
        updates.append("title = ?"); params.append(body.title)
    if body.slug is not None:
        new_slug = _unique_slug(_slugify(body.slug), exclude_id=runbook_id)
        updates.append("slug = ?"); params.append(new_slug)
    if body.category is not None:
        updates.append("category = ?"); params.append(body.category)
    if body.tags is not None:
        updates.append("tags = ?"); params.append(body.tags)
    if body.owner is not None:
        updates.append("owner = ?"); params.append(body.owner)
    if body.linked_playbook_id is not None:
        updates.append("linked_playbook_id = ?"); params.append(body.linked_playbook_id)
    content_changed = body.content_md is not None
    if content_changed:
        updates.append("content_md = ?"); params.append(body.content_md)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at = ?"); params.append(_now())
    params.append(runbook_id)
    try:
        con = _conn()
        con.execute(f"UPDATE runbooks SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "Runbook not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if content_changed and body.content_md is not None:
        ver_num = _save_version(
            runbook_id, body.content_md,
            body.edited_by or "unknown", body.change_note or "Updated",
        )
        return {"ok": True, "version_number": ver_num}
    return {"ok": True}


@router.delete("/{runbook_id}", status_code=204, summary="Delete runbook and all versions")
async def delete_runbook(runbook_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM runbook_versions WHERE runbook_id=?", (runbook_id,))
        con.execute("DELETE FROM runbooks WHERE id=?", (runbook_id,))
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.get("/{runbook_id}/versions", summary="Version history")
async def list_versions(
    runbook_id: str,
    limit: int = Query(100, ge=1, le=500),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        exists = con.execute("SELECT id FROM runbooks WHERE id=?", (runbook_id,)).fetchone()
        if not exists:
            con.close()
            raise HTTPException(404, "Runbook not found")
        rows = con.execute(
            "SELECT id, runbook_id, version_number, edited_by, edited_at, change_note "
            "FROM runbook_versions WHERE runbook_id=? ORDER BY version_number DESC LIMIT ?",
            (runbook_id, limit),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    cols = ["id", "runbook_id", "version_number", "edited_by", "edited_at", "change_note"]
    return {"versions": [dict(zip(cols, r)) for r in rows]}


@router.get("/{runbook_id}/versions/{version_number}", summary="Specific version content")
async def get_version(
    runbook_id: str, version_number: int, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_VER_COLS)} FROM runbook_versions "
            "WHERE runbook_id=? AND version_number=?",
            (runbook_id, version_number),
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not row:
        raise HTTPException(404, "Version not found")
    return dict(zip(_VER_COLS, row))
