"""Tests for backend/api/knowledge_base.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.knowledge_base as kb_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "kb_test.db")
    monkeypatch.setattr(kb_mod, "_DB_PATH", db_path)
    kb_mod._init_db()

    app = FastAPI()
    app.include_router(kb_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"title": "How to restart nginx", **kwargs}
    r = c.post("/api/v1/kb/articles", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, art_id, status, **kwargs):
    return c.post(f"/api/v1/kb/articles/{art_id}/transition",
                  json={"status": status, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="Deploy guide", category="ops",
                tags="deploy,guide", author="alice", body="Step 1...")
    art_id = d["id"]
    assert d["status"] == "draft"
    assert d["slug"]

    r = c.get(f"/api/v1/kb/articles/{art_id}")
    assert r.status_code == 200
    a = r.json()
    assert a["title"] == "Deploy guide"
    assert a["category"] == "ops"
    assert a["tags"] == "deploy,guide"
    assert a["author"] == "alice"
    assert a["status"] == "draft"
    assert a["published_at"] is None


def test_get_increments_views(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    art_id = d["id"]
    assert c.get(f"/api/v1/kb/articles/{art_id}").json()["views"] == 1
    assert c.get(f"/api/v1/kb/articles/{art_id}").json()["views"] == 2
    assert c.get(f"/api/v1/kb/articles/{art_id}").json()["views"] == 3


def test_slug_auto_generated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="Hello World Article")
    assert d["slug"] == "hello-world-article"


def test_slug_dedup_on_collision(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, title="Same Title")
    d2 = _create(c, title="Same Title")
    assert d1["slug"] != d2["slug"]
    assert d2["slug"].startswith("same-title")


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Alpha article")
    _create(c, title="Beta article")
    r = c.get("/api/v1/kb/articles")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, title="A")
    _create(c, title="B")
    _transition(c, d1["id"], "review")
    r = c.get("/api/v1/kb/articles?status=review")
    assert r.json()["total"] == 1
    assert r.json()["articles"][0]["id"] == d1["id"]


def test_list_filter_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Ops guide", category="ops")
    _create(c, title="Dev guide", category="dev")
    r = c.get("/api/v1/kb/articles?category=ops")
    assert r.json()["total"] == 1
    assert r.json()["articles"][0]["category"] == "ops"


def test_list_search_title(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="nginx configuration", body="server block...")
    _create(c, title="postgres backup", body="pg_dump...")
    r = c.get("/api/v1/kb/articles?q=nginx")
    assert r.json()["total"] == 1


def test_list_search_body(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="guide A", body="Contains special keyword xyzzy")
    _create(c, title="guide B", body="Regular content")
    r = c.get("/api/v1/kb/articles?q=xyzzy")
    assert r.json()["total"] == 1


def test_list_search_tags(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="A", tags="critical,urgent")
    _create(c, title="B", tags="low-priority")
    r = c.get("/api/v1/kb/articles?q=critical")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, title=f"Article {i}")
    r = c.get("/api/v1/kb/articles?limit=3&offset=0")
    assert len(r.json()["articles"]) == 3
    r2 = c.get("/api/v1/kb/articles?limit=3&offset=3")
    assert len(r2.json()["articles"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="Old Title")
    r = c.patch(f"/api/v1/kb/articles/{d['id']}", json={
        "title": "New Title", "category": "security", "body": "Updated body."
    })
    assert r.status_code == 200
    a = c.get(f"/api/v1/kb/articles/{d['id']}").json()
    assert a["title"] == "New Title"
    assert a["category"] == "security"
    assert a["body"] == "Updated body."


def test_patch_updates_slug(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="Old Title")
    c.patch(f"/api/v1/kb/articles/{d['id']}", json={"title": "Brand New Title"})
    a = c.get(f"/api/v1/kb/articles/{d['id']}").json()
    assert a["slug"] == "brand-new-title"


def test_delete_removes_article(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/kb/articles/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/kb/articles/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/kb/articles/no-such-id").status_code == 404


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_draft_to_review(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "review")
    assert r.status_code == 200
    assert c.get(f"/api/v1/kb/articles/{d['id']}").json()["status"] == "review"


def test_transition_review_to_published(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "review")
    r = _transition(c, d["id"], "published")
    assert r.status_code == 200
    assert c.get(f"/api/v1/kb/articles/{d['id']}").json()["status"] == "published"


def test_transition_review_back_to_draft(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "review")
    r = _transition(c, d["id"], "draft")
    assert r.status_code == 200


def test_transition_published_to_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "review")
    _transition(c, d["id"], "published")
    r = _transition(c, d["id"], "archived")
    assert r.status_code == 200
    assert c.get(f"/api/v1/kb/articles/{d['id']}").json()["status"] == "archived"


def test_transition_archived_to_draft(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "archived")
    r = _transition(c, d["id"], "draft")
    assert r.status_code == 200
    assert c.get(f"/api/v1/kb/articles/{d['id']}").json()["status"] == "draft"


def test_transition_draft_to_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "archived")
    assert r.status_code == 200


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "published")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "vaporized")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "review")
    assert r.status_code == 404


# ── published_at auto-timestamp ───────────────────────────────────────────────

def test_published_at_set_on_publish(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "review")
    _transition(c, d["id"], "published")
    a = c.get(f"/api/v1/kb/articles/{d['id']}").json()
    assert a["published_at"] is not None


def test_published_at_cleared_on_unpublish(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "review")
    _transition(c, d["id"], "published")
    _transition(c, d["id"], "draft")
    a = c.get(f"/api/v1/kb/articles/{d['id']}").json()
    assert a["published_at"] is None


def test_published_at_cleared_on_archive(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "review")
    _transition(c, d["id"], "published")
    _transition(c, d["id"], "archived")
    a = c.get(f"/api/v1/kb/articles/{d['id']}").json()
    assert a["published_at"] is None


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/kb/articles/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["published"] == 0


def test_stats_published_count(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, title="A")
    d2 = _create(c, title="B")
    _create(c, title="C")
    _transition(c, d1["id"], "review"); _transition(c, d1["id"], "published")
    _transition(c, d2["id"], "review"); _transition(c, d2["id"], "published")
    r = c.get("/api/v1/kb/articles/stats")
    assert r.json()["published"] == 2


def test_stats_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="A", category="ops")
    _create(c, title="B", category="ops")
    _create(c, title="C", category="dev")
    r = c.get("/api/v1/kb/articles/stats")
    by_cat = {x["category"]: x["count"] for x in r.json()["by_category"]}
    assert by_cat.get("ops", 0) == 2
    assert by_cat.get("dev", 0) == 1


def test_stats_most_viewed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, title="Popular")
    _create(c, title="Unknown")
    _transition(c, d1["id"], "review"); _transition(c, d1["id"], "published")
    for _ in range(5):
        c.get(f"/api/v1/kb/articles/{d1['id']}")
    r = c.get("/api/v1/kb/articles/stats")
    assert r.json()["most_viewed"][0]["id"] == d1["id"]


# ── Revisions ─────────────────────────────────────────────────────────────────

def test_save_and_list_revisions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="Guide v1", body="Original body")
    r = c.post(f"/api/v1/kb/articles/{d['id']}/revisions", json={"author": "alice"})
    assert r.status_code == 201
    revs = c.get(f"/api/v1/kb/articles/{d['id']}/revisions").json()["revisions"]
    assert len(revs) == 1
    assert revs[0]["title"] == "Guide v1"
    assert revs[0]["body"] == "Original body"


def test_multiple_revisions_accumulate(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="Doc")
    c.post(f"/api/v1/kb/articles/{d['id']}/revisions", json={})
    c.patch(f"/api/v1/kb/articles/{d['id']}", json={"body": "v2 body"})
    c.post(f"/api/v1/kb/articles/{d['id']}/revisions", json={})
    revs = c.get(f"/api/v1/kb/articles/{d['id']}/revisions").json()["revisions"]
    assert len(revs) == 2


def test_revisions_on_nonexistent_article_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/kb/articles/no-id/revisions", json={})
    assert r.status_code == 404


# ── Cascade delete ─────────────────────────────────────────────────────────────

def test_delete_cascades_revisions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="To delete")
    art_id = d["id"]
    c.post(f"/api/v1/kb/articles/{art_id}/revisions", json={})
    c.delete(f"/api/v1/kb/articles/{art_id}")
    con = sqlite3.connect(kb_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM kb_revisions WHERE article_id=?", (art_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0
