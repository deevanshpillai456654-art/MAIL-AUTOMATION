"""Tests for backend/api/runbooks.py"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── helpers ──────────────────────────────────────────────────────────────────

def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = str(tmp_path / "runbooks.db")
    # Reload module with patched DB path
    if "backend.api.runbooks" in sys.modules:
        del sys.modules["backend.api.runbooks"]
    monkeypatch.setenv("__RB_TEST_DB__", db)

    import backend.api.runbooks as rb_mod
    monkeypatch.setattr(rb_mod, "_DB_PATH", db)
    rb_mod._init_db()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.include_router(rb_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: "test"
    return TestClient(app, raise_server_exceptions=True)


# ── slugify ───────────────────────────────────────────────────────────────────

def test_slugify_basic():
    from backend.api.runbooks import _slugify
    assert _slugify("Hello World") == "hello-world"


def test_slugify_special_chars():
    from backend.api.runbooks import _slugify
    assert _slugify("DB Failover! #1") == "db-failover-1"


def test_slugify_multiple_spaces():
    from backend.api.runbooks import _slugify
    assert _slugify("  too   many   spaces  ") == "too-many-spaces"


def test_slugify_empty_fallback():
    from backend.api.runbooks import _slugify
    assert _slugify("!!!") == "runbook"


def test_slugify_hyphens():
    from backend.api.runbooks import _slugify
    assert _slugify("already-hyphenated") == "already-hyphenated"


# ── unique_slug ───────────────────────────────────────────────────────────────

def test_unique_slug_no_conflict(tmp_path, monkeypatch):
    db = str(tmp_path / "runbooks.db")
    if "backend.api.runbooks" in sys.modules:
        del sys.modules["backend.api.runbooks"]
    import backend.api.runbooks as rb_mod
    monkeypatch.setattr(rb_mod, "_DB_PATH", db)
    rb_mod._init_db()
    assert rb_mod._unique_slug("my-runbook") == "my-runbook"


def test_unique_slug_collision(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    import backend.api.runbooks as rb_mod
    # Insert a runbook manually so slug "proc" is taken
    import sqlite3, uuid
    now = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(rb_mod._DB_PATH) as con:
        con.execute(
            "INSERT INTO runbooks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), "Proc", "proc", "", "", "", "", None, now, now, 0),
        )
    slug = rb_mod._unique_slug("proc")
    assert slug == "proc-1"


def test_unique_slug_exclude_self(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    import backend.api.runbooks as rb_mod
    import sqlite3, uuid
    now = "2026-01-01T00:00:00+00:00"
    rb_id = str(uuid.uuid4())
    with sqlite3.connect(rb_mod._DB_PATH) as con:
        con.execute(
            "INSERT INTO runbooks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (rb_id, "Proc", "proc", "", "", "", "", None, now, now, 0),
        )
    # Same runbook excluded — slug stays the same
    assert rb_mod._unique_slug("proc", exclude_id=rb_id) == "proc"


# ── create / list ─────────────────────────────────────────────────────────────

def test_create_runbook(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/runbooks", json={"title": "My Runbook", "content_md": "# Hello"})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "My Runbook"
    assert body["slug"] == "my-runbook"
    assert "id" in body


def test_create_auto_slug_from_title(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/runbooks", json={"title": "DB Failover Procedure"})
    assert r.status_code == 201
    assert r.json()["slug"] == "db-failover-procedure"


def test_create_explicit_slug(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/runbooks", json={"title": "Test", "slug": "custom-slug"})
    assert r.status_code == 201
    assert r.json()["slug"] == "custom-slug"


def test_create_slug_dedup(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/v1/runbooks", json={"title": "Alpha"})
    r = c.post("/api/v1/runbooks", json={"title": "Alpha"})
    assert r.status_code == 201
    assert r.json()["slug"] == "alpha-1"


def test_list_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/runbooks")
    assert r.status_code == 200
    assert r.json()["runbooks"] == []
    assert r.json()["total"] == 0


def test_list_returns_preview_not_content(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    long_md = "X" * 500
    c.post("/api/v1/runbooks", json={"title": "Big", "content_md": long_md})
    r = c.get("/api/v1/runbooks")
    rb = r.json()["runbooks"][0]
    assert "content_md" not in rb
    assert "content_preview" in rb
    assert len(rb["content_preview"]) <= 200


def test_list_tags_as_list(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/v1/runbooks", json={"title": "Tagged", "tags": "ops, infra, db"})
    r = c.get("/api/v1/runbooks")
    rb = r.json()["runbooks"][0]
    assert rb["tags"] == ["ops", "infra", "db"]


def test_list_search_by_title(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/v1/runbooks", json={"title": "Alpha Runbook"})
    c.post("/api/v1/runbooks", json={"title": "Beta Runbook"})
    r = c.get("/api/v1/runbooks?q=Alpha")
    assert r.json()["total"] == 1
    assert r.json()["runbooks"][0]["title"] == "Alpha Runbook"


def test_list_filter_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/v1/runbooks", json={"title": "Infra Doc", "category": "infra"})
    c.post("/api/v1/runbooks", json={"title": "Dev Doc", "category": "dev"})
    r = c.get("/api/v1/runbooks?category=infra")
    assert r.json()["total"] == 1
    assert r.json()["runbooks"][0]["title"] == "Infra Doc"


def test_list_filter_by_tag(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/v1/runbooks", json={"title": "With Tag", "tags": "database"})
    c.post("/api/v1/runbooks", json={"title": "No Tag"})
    r = c.get("/api/v1/runbooks?tag=database")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        c.post("/api/v1/runbooks", json={"title": f"RB {i}"})
    r = c.get("/api/v1/runbooks?limit=2&offset=0")
    assert len(r.json()["runbooks"]) == 2
    assert r.json()["total"] == 5


# ── get detail ────────────────────────────────────────────────────────────────

def test_get_by_id(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Detail Test", "content_md": "body"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "Detail Test"
    assert r.json()["content_md"] == "body"


def test_get_by_slug(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/v1/runbooks", json={"title": "Slug Test"})
    r = c.get("/api/v1/runbooks/slug-test")
    assert r.status_code == 200
    assert r.json()["title"] == "Slug Test"


def test_get_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/runbooks/nonexistent")
    assert r.status_code == 404


def test_get_increments_view_count(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Viewed"}).json()["id"]
    # view_count is read then incremented; 4th GET observes the 3 prior increments
    c.get(f"/api/v1/runbooks/{rb_id}")
    c.get(f"/api/v1/runbooks/{rb_id}")
    c.get(f"/api/v1/runbooks/{rb_id}")
    r = c.get(f"/api/v1/runbooks/{rb_id}")
    assert r.json()["view_count"] == 3


def test_get_latest_version_metadata(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Versioned", "content_md": "v1"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}")
    assert r.json()["latest_version"] is not None
    assert r.json()["latest_version"]["version_number"] == 1


def test_get_tags_as_list(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Tagged RB", "tags": "a, b, c"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}")
    assert set(r.json()["tags"]) == {"a", "b", "c"}


# ── patch ─────────────────────────────────────────────────────────────────────

def test_patch_title(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Original"}).json()["id"]
    r = c.patch(f"/api/v1/runbooks/{rb_id}", json={"title": "Updated"})
    assert r.status_code == 200
    detail = c.get(f"/api/v1/runbooks/{rb_id}").json()
    assert detail["title"] == "Updated"


def test_patch_content_creates_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Versioned", "content_md": "v1"}).json()["id"]
    r = c.patch(f"/api/v1/runbooks/{rb_id}", json={"content_md": "v2", "edited_by": "alice", "change_note": "Updated body"})
    assert r.status_code == 200
    assert r.json()["version_number"] == 2


def test_patch_no_content_no_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Versioned", "content_md": "v1"}).json()["id"]
    r = c.patch(f"/api/v1/runbooks/{rb_id}", json={"title": "Retitled"})
    assert r.status_code == 200
    assert "version_number" not in r.json()


def test_patch_empty_body_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "T"}).json()["id"]
    r = c.patch(f"/api/v1/runbooks/{rb_id}", json={})
    assert r.status_code == 400


def test_patch_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/api/v1/runbooks/missing", json={"title": "X"})
    assert r.status_code == 404


def test_patch_slug_changes_slug(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Old"}).json()["id"]
    c.patch(f"/api/v1/runbooks/{rb_id}", json={"slug": "new-slug"})
    r = c.get(f"/api/v1/runbooks/new-slug")
    assert r.status_code == 200


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete_runbook(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "To Delete"}).json()["id"]
    r = c.delete(f"/api/v1/runbooks/{rb_id}")
    assert r.status_code == 204
    assert c.get(f"/api/v1/runbooks/{rb_id}").status_code == 404


def test_delete_removes_versions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    import backend.api.runbooks as rb_mod
    import sqlite3
    rb_id = c.post("/api/v1/runbooks", json={"title": "With Vers", "content_md": "v1"}).json()["id"]
    c.delete(f"/api/v1/runbooks/{rb_id}")
    with sqlite3.connect(rb_mod._DB_PATH) as con:
        count = con.execute("SELECT COUNT(*) FROM runbook_versions WHERE runbook_id=?", (rb_id,)).fetchone()[0]
    assert count == 0


# ── stats ─────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/runbooks/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["total_versions"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Stat RB", "content_md": "body", "category": "ops"}).json()["id"]
    c.patch(f"/api/v1/runbooks/{rb_id}", json={"content_md": "body2"})
    r = c.get("/api/v1/runbooks/stats")
    assert r.json()["total"] == 1
    assert r.json()["total_versions"] == 2
    cats = {x["category"]: x["count"] for x in r.json()["by_category"]}
    assert cats.get("ops") == 1


def test_stats_top_viewed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Popular"}).json()["id"]
    for _ in range(3):
        c.get(f"/api/v1/runbooks/{rb_id}")
    r = c.get("/api/v1/runbooks/stats")
    assert r.json()["top_viewed"][0]["views"] == 3


# ── categories ────────────────────────────────────────────────────────────────

def test_categories_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/runbooks/categories")
    assert r.json()["categories"] == []


def test_categories_distinct(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api/v1/runbooks", json={"title": "A", "category": "infra"})
    c.post("/api/v1/runbooks", json={"title": "B", "category": "infra"})
    c.post("/api/v1/runbooks", json={"title": "C", "category": "dev"})
    r = c.get("/api/v1/runbooks/categories")
    assert set(r.json()["categories"]) == {"infra", "dev"}


# ── versions ─────────────────────────────────────────────────────────────────

def test_version_saved_on_create_with_content(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "V1", "content_md": "body"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}/versions")
    assert r.status_code == 200
    assert len(r.json()["versions"]) == 1
    assert r.json()["versions"][0]["version_number"] == 1


def test_version_not_saved_without_content(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "No Content"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}/versions")
    assert len(r.json()["versions"]) == 0


def test_versions_incremented(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Multi", "content_md": "v1"}).json()["id"]
    c.patch(f"/api/v1/runbooks/{rb_id}", json={"content_md": "v2"})
    c.patch(f"/api/v1/runbooks/{rb_id}", json={"content_md": "v3"})
    r = c.get(f"/api/v1/runbooks/{rb_id}/versions")
    nums = [v["version_number"] for v in r.json()["versions"]]
    assert sorted(nums) == [1, 2, 3]


def test_versions_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/runbooks/nonexistent/versions")
    assert r.status_code == 404


def test_get_specific_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Spec", "content_md": "original"}).json()["id"]
    c.patch(f"/api/v1/runbooks/{rb_id}", json={"content_md": "updated"})
    r = c.get(f"/api/v1/runbooks/{rb_id}/versions/1")
    assert r.status_code == 200
    assert r.json()["content_md"] == "original"
    assert r.json()["version_number"] == 1


def test_get_specific_version_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "T", "content_md": "x"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}/versions/99")
    assert r.status_code == 404


def test_version_change_note(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "Noted", "content_md": "v1", "owner": "ops"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}/versions/1")
    assert r.json()["change_note"] == "Initial version"


def test_version_list_excludes_content(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    rb_id = c.post("/api/v1/runbooks", json={"title": "T", "content_md": "body"}).json()["id"]
    r = c.get(f"/api/v1/runbooks/{rb_id}/versions")
    # list endpoint omits content_md to keep responses lean
    assert "content_md" not in r.json()["versions"][0]
