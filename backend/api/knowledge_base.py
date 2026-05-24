"""
Knowledge Base
==============
Article registry with 4-state lifecycle, auto-slug generation,
revision snapshots, and view counting.

Tables:
  kb_articles   — article records (slug UNIQUE)
  kb_revisions  — immutable point-in-time snapshots

State machine:
  draft     → review | archived
  review    → published | draft
  published → archived | draft
  archived  → draft

Auto-timestamps:
  published_at  set on → published; cleared on → draft | archived

Endpoints:
  GET    /kb/articles
  POST   /kb/articles                         (201)
  GET    /kb/articles/stats
  GET    /kb/articles/{article_id}            (increments views)
  PATCH  /kb/articles/{article_id}
  DELETE /kb/articles/{article_id}            (204)
  POST   /kb/articles/{article_id}/transition
  GET    /kb/articles/{article_id}/revisions
  POST   /kb/articles/{article_id}/revisions  (201)
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
router = APIRouter(prefix="/kb", tags=["knowledge_base"])

_DB_PATH = str(Path(DATA_DIR) / "knowledge_base.db")

_ART_COLS = [
    "id", "title", "slug", "body", "category", "tags",
    "status", "author", "views", "published_at",
    "created_at", "updated_at",
]
_REV_COLS = ["id", "article_id", "title", "body", "author", "created_at"]

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":     {"review", "archived"},
    "review":    {"published", "draft"},
    "published": {"archived", "draft"},
    "archived":  {"draft"},
}
_VALID_STATUSES = set(_VALID_TRANSITIONS.keys())


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS kb_articles (
            id           TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            slug         TEXT NOT NULL UNIQUE,
            body         TEXT NOT NULL DEFAULT '',
            category     TEXT NOT NULL DEFAULT '',
            tags         TEXT NOT NULL DEFAULT '',
            status       TEXT NOT NULL DEFAULT 'draft',
            author       TEXT NOT NULL DEFAULT '',
            views        INTEGER NOT NULL DEFAULT 0,
            published_at TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS kb_revisions (
            id         TEXT PRIMARY KEY,
            article_id TEXT NOT NULL,
            title      TEXT NOT NULL,
            body       TEXT NOT NULL DEFAULT '',
            author     TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_kb_status   ON kb_articles (status);
        CREATE INDEX IF NOT EXISTS idx_kb_category ON kb_articles (category);
        CREATE INDEX IF NOT EXISTS idx_kb_slug     ON kb_articles (slug);
        CREATE INDEX IF NOT EXISTS idx_kb_updated  ON kb_articles (updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_rev_art     ON kb_revisions (article_id, created_at DESC);
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
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "article"


def _unique_slug(con: sqlite3.Connection, base: str, exclude_id: str = "") -> str:
    slug, n = base, 1
    while True:
        row = con.execute(
            "SELECT id FROM kb_articles WHERE slug=?", (slug,)
        ).fetchone()
        if not row or row[0] == exclude_id:
            return slug
        slug = f"{base}-{n}"; n += 1


def _get_art_or_404(con: sqlite3.Connection, article_id: str) -> tuple:
    row = con.execute(
        f"SELECT {','.join(_ART_COLS)} FROM kb_articles WHERE id=?",
        (article_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Article not found")
    return row


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ArticleCreate(BaseModel):
    title:    str
    body:     str           = ""
    category: str           = ""
    tags:     str           = ""
    author:   str           = ""


class ArticlePatch(BaseModel):
    title:    Optional[str] = None
    body:     Optional[str] = None
    category: Optional[str] = None
    tags:     Optional[str] = None
    author:   Optional[str] = None


class TransitionBody(BaseModel):
    status: str
    author: str = ""


class RevisionCreate(BaseModel):
    author: str = ""


# ── List / create ─────────────────────────────────────────────────────────────

@router.get("/articles", summary="List articles")
async def list_articles(
    q:        Optional[str] = Query(None),
    status:   Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    where, params = [], []
    if q:
        where.append("(title LIKE ? OR body LIKE ? OR tags LIKE ? OR category LIKE ?)")
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
            f"SELECT COUNT(*) FROM kb_articles {clause}", params
        ).fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_ART_COLS)} FROM kb_articles {clause} "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {
        "articles": [dict(zip(_ART_COLS, r)) for r in rows],
        "total": total, "limit": limit, "offset": offset,
    }


@router.post("/articles", status_code=201, summary="Create article")
async def create_article(body: ArticleCreate, _auth=Depends(require_local_auth)):
    article_id = str(uuid.uuid4())
    now        = _now()
    try:
        con  = _conn()
        slug = _unique_slug(con, _slugify(body.title))
        con.execute(
            f"INSERT INTO kb_articles ({','.join(_ART_COLS)}) "
            f"VALUES ({','.join(['?']*len(_ART_COLS))})",
            (article_id, body.title, slug, body.body, body.category,
             body.tags, "draft", body.author, 0, None, now, now),
        )
        con.commit()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"id": article_id, "slug": slug, "status": "draft"}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/articles/stats", summary="Knowledge base statistics")
async def kb_stats(_auth=Depends(require_local_auth)):
    try:
        con       = _conn()
        total     = con.execute("SELECT COUNT(*) FROM kb_articles").fetchone()[0]
        published = con.execute(
            "SELECT COUNT(*) FROM kb_articles WHERE status='published'"
        ).fetchone()[0]
        by_status = con.execute(
            "SELECT status, COUNT(*) FROM kb_articles GROUP BY status"
        ).fetchall()
        by_cat    = con.execute(
            "SELECT category, COUNT(*) FROM kb_articles "
            "WHERE category != '' GROUP BY category ORDER BY COUNT(*) DESC"
        ).fetchall()
        most_viewed = con.execute(
            f"SELECT {','.join(_ART_COLS)} FROM kb_articles "
            "WHERE status='published' ORDER BY views DESC LIMIT 5"
        ).fetchall()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {
        "total":       total,
        "published":   published,
        "by_status":   [{"status": s, "count": c} for s, c in by_status],
        "by_category": [{"category": cat, "count": c} for cat, c in by_cat],
        "most_viewed": [dict(zip(_ART_COLS, r)) for r in most_viewed],
    }


# ── Single article ────────────────────────────────────────────────────────────

@router.get("/articles/{article_id}", summary="Get article (increments view count)")
async def get_article(article_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_art_or_404(con, article_id)
        con.execute(
            "UPDATE kb_articles SET views = views + 1 WHERE id=?", (article_id,)
        )
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_ART_COLS)} FROM kb_articles WHERE id=?",
            (article_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return dict(zip(_ART_COLS, row))


@router.patch("/articles/{article_id}", summary="Update article")
async def patch_article(
    article_id: str, body: ArticlePatch, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        row = _get_art_or_404(con, article_id)
        d   = dict(zip(_ART_COLS, row))
        sets, params = ["updated_at=?"], [_now()]
        for field in ("body", "category", "tags", "author"):
            val = getattr(body, field)
            if val is not None:
                sets.append(f"{field}=?")
                params.append(val)
        if body.title is not None:
            new_slug = _unique_slug(con, _slugify(body.title), exclude_id=article_id)
            sets += ["title=?", "slug=?"]
            params += [body.title, new_slug]
        params.append(article_id)
        con.execute(f"UPDATE kb_articles SET {','.join(sets)} WHERE id=?", params)
        con.commit()
        row = con.execute(
            f"SELECT {','.join(_ART_COLS)} FROM kb_articles WHERE id=?",
            (article_id,),
        ).fetchone()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return dict(zip(_ART_COLS, row))


@router.delete("/articles/{article_id}", status_code=204, summary="Delete article")
async def delete_article(article_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        _get_art_or_404(con, article_id)
        con.execute("DELETE FROM kb_revisions WHERE article_id=?", (article_id,))
        con.execute("DELETE FROM kb_articles WHERE id=?", (article_id,))
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")


# ── Transitions ───────────────────────────────────────────────────────────────

@router.post("/articles/{article_id}/transition", summary="Transition article status")
async def transition_article(
    article_id: str, body: TransitionBody, _auth=Depends(require_local_auth)
):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            400, f"Unknown status '{body.status}'. Valid: {sorted(_VALID_STATUSES)}"
        )
    try:
        con = _conn()
        row = _get_art_or_404(con, article_id)
        d   = dict(zip(_ART_COLS, row))
        current = d["status"]
        if body.status not in _VALID_TRANSITIONS[current]:
            allowed = sorted(_VALID_TRANSITIONS[current])
            raise HTTPException(
                400, f"Cannot move from '{current}' to '{body.status}'. Allowed: {allowed}"
            )
        now  = _now()
        sets = ["status=?", "updated_at=?"]
        vals = [body.status, now]
        if body.status == "published":
            sets.append("published_at=?"); vals.append(now)
        elif body.status in {"draft", "archived"}:
            sets.append("published_at=?"); vals.append(None)
        vals.append(article_id)
        con.execute(f"UPDATE kb_articles SET {','.join(sets)} WHERE id=?", vals)
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"ok": True, "status": body.status}


# ── Revisions ─────────────────────────────────────────────────────────────────

@router.get("/articles/{article_id}/revisions", summary="List article revisions")
async def list_revisions(
    article_id: str,
    limit: int = Query(100, ge=1, le=500),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        _get_art_or_404(con, article_id)
        rows = con.execute(
            f"SELECT {','.join(_REV_COLS)} FROM kb_revisions "
            "WHERE article_id=? ORDER BY created_at DESC LIMIT ?",
            (article_id, limit),
        ).fetchall()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"revisions": [dict(zip(_REV_COLS, r)) for r in rows]}


@router.post("/articles/{article_id}/revisions", status_code=201,
             summary="Save current article state as a revision")
async def save_revision(
    article_id: str, body: RevisionCreate, _auth=Depends(require_local_auth)
):
    try:
        con = _conn()
        row = _get_art_or_404(con, article_id)
        d   = dict(zip(_ART_COLS, row))
        rev_id = str(uuid.uuid4())
        now    = _now()
        con.execute(
            f"INSERT INTO kb_revisions ({','.join(_REV_COLS)}) "
            f"VALUES ({','.join(['?']*len(_REV_COLS))})",
            (rev_id, article_id, d["title"], d["body"], body.author, now),
        )
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"id": rev_id, "ok": True}
