"""Tests for backend/api/config_management.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.config_management as cm_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cfg_test.db")
    monkeypatch.setattr(cm_mod, "_DB_PATH", db_path)
    cm_mod._init_db()

    app = FastAPI()
    app.include_router(cm_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"key": "app.max_retries", "value": "3", **kwargs}
    r = c.post("/api/v1/configs", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, cfg_id, status, **kwargs):
    return c.post(f"/api/v1/configs/{cfg_id}/transition",
                  json={"status": status, **kwargs})


def _patch(c, cfg_id, **kwargs):
    return c.patch(f"/api/v1/configs/{cfg_id}", json=kwargs)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, key="feature.timeout", value="30", environment="production",
                type="number", description="Request timeout in seconds",
                owner="platform-team", tags="timeouts,network")
    cfg_id = d["id"]
    assert d["status"] == "active"
    assert d["key"] == "feature.timeout"
    assert d["environment"] == "production"

    r = c.get(f"/api/v1/configs/{cfg_id}")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["key"] == "feature.timeout"
    assert cfg["value"] == "30"
    assert cfg["type"] == "number"
    assert cfg["description"] == "Request timeout in seconds"
    assert cfg["owner"] == "platform-team"
    assert cfg["status"] == "active"
    assert cfg["version_count"] == 1


def test_create_defaults(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.get(f"/api/v1/configs/{d['id']}").json()
    assert r["environment"] == "production"
    assert r["type"] == "string"
    assert r["status"] == "active"


def test_create_seeds_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, value="initial_value")
    vers = c.get(f"/api/v1/configs/{d['id']}/versions").json()["versions"]
    assert len(vers) == 1
    assert vers[0]["value"] == "initial_value"
    assert vers[0]["note"] == "initial value"


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="a.b", environment="production")
    _create(c, key="c.d", environment="staging")
    r = c.get("/api/v1/configs")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_filter_by_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="x.y", environment="production")
    _create(c, key="x.y", environment="staging")
    r = c.get("/api/v1/configs?environment=production")
    assert r.json()["total"] == 1
    assert r.json()["configs"][0]["environment"] == "production"


def test_list_filter_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="a", type="number", environment="production")
    _create(c, key="b", type="string", environment="staging")
    r = c.get("/api/v1/configs?type=number")
    assert r.json()["total"] == 1


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, key="a", environment="production")
    _create(c, key="b", environment="staging")
    _transition(c, d1["id"], "deprecated")
    r = c.get("/api/v1/configs?status=deprecated")
    assert r.json()["total"] == 1


def test_list_search_by_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="feature.dark_mode", environment="production")
    _create(c, key="infra.timeout", environment="production")
    r = c.get("/api/v1/configs?q=dark_mode")
    assert r.json()["total"] == 1


def test_list_search_by_owner(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="a", environment="production", owner="platform-team")
    _create(c, key="b", environment="staging", owner="devops")
    r = c.get("/api/v1/configs?q=platform-team")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, key=f"key.{i}", environment=f"env{i}")
    r = c.get("/api/v1/configs?limit=3&offset=0")
    assert len(r.json()["configs"]) == 3
    r2 = c.get("/api/v1/configs?limit=3&offset=3")
    assert len(r2.json()["configs"]) == 2


def test_list_includes_version_count(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, key="k", environment="production", value="v1")
    _patch(c, d["id"], value="v2")
    r = c.get("/api/v1/configs").json()["configs"][0]
    assert r["version_count"] == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, key="k", environment="production")
    r = _patch(c, d["id"], description="Updated desc", owner="new-team")
    assert r.status_code == 200
    cfg = c.get(f"/api/v1/configs/{d['id']}").json()
    assert cfg["description"] == "Updated desc"
    assert cfg["owner"] == "new-team"


def test_patch_value_creates_new_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, value="old_val")
    _patch(c, d["id"], value="new_val", changed_by="ci-bot", note="bump for release")
    vers = c.get(f"/api/v1/configs/{d['id']}/versions").json()["versions"]
    assert len(vers) == 2
    assert vers[0]["value"] == "new_val"
    assert vers[0]["changed_by"] == "ci-bot"
    assert vers[0]["note"] == "bump for release"


def test_patch_same_value_no_new_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, value="same_val")
    _patch(c, d["id"], value="same_val")
    vers = c.get(f"/api/v1/configs/{d['id']}/versions").json()["versions"]
    assert len(vers) == 1


def test_patch_non_value_fields_no_new_version(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, value="v1")
    _patch(c, d["id"], owner="new-owner")
    vers = c.get(f"/api/v1/configs/{d['id']}/versions").json()["versions"]
    assert len(vers) == 1


def test_delete_removes_config(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/configs/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/configs/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/configs/no-id").status_code == 404


def test_duplicate_key_environment_returns_409(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="app.timeout", environment="production")
    r = c.post("/api/v1/configs", json={"key": "app.timeout", "environment": "production"})
    assert r.status_code == 409


def test_same_key_different_environment_allowed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="app.timeout", environment="production")
    r = c.post("/api/v1/configs", json={"key": "app.timeout", "environment": "staging"})
    assert r.status_code == 201


def test_invalid_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/configs", json={"key": "x", "type": "yaml"})
    assert r.status_code == 400


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_active_to_deprecated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "deprecated")
    assert r.status_code == 200
    assert c.get(f"/api/v1/configs/{d['id']}").json()["status"] == "deprecated"


def test_transition_deprecated_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "deprecated")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_transition_active_to_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "archived")
    assert r.status_code == 200
    assert c.get(f"/api/v1/configs/{d['id']}").json()["status"] == "archived"


def test_transition_deprecated_to_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "deprecated")
    r = _transition(c, d["id"], "archived")
    assert r.status_code == 200


def test_archived_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "archived")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "published")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "deprecated")
    assert r.status_code == 404


# ── Versions ──────────────────────────────────────────────────────────────────

def test_versions_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, value="v0")
    for i in range(1, 5):
        _patch(c, d["id"], value=f"v{i}")
    r = c.get(f"/api/v1/configs/{d['id']}/versions?limit=3&offset=0")
    assert r.status_code == 200
    assert len(r.json()["versions"]) == 3
    assert r.json()["total"] == 5


def test_versions_nonexistent_config_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/configs/no-id/versions")
    assert r.status_code == 404


# ── Promote ───────────────────────────────────────────────────────────────────

def test_promote_to_new_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, key="app.timeout", value="30", environment="staging",
                type="number", owner="ops")
    r = c.post(f"/api/v1/configs/{d['id']}/promote",
               json={"target_environment": "production", "changed_by": "ci-bot"})
    assert r.status_code == 201
    new_id = r.json()["id"]
    promoted = c.get(f"/api/v1/configs/{new_id}").json()
    assert promoted["key"] == "app.timeout"
    assert promoted["value"] == "30"
    assert promoted["environment"] == "production"
    assert promoted["type"] == "number"
    assert promoted["status"] == "active"
    assert promoted["version_count"] == 1


def test_promote_seeds_version_with_note(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, key="k", environment="dev")
    r = c.post(f"/api/v1/configs/{d['id']}/promote",
               json={"target_environment": "staging",
                     "changed_by": "deploy-bot", "note": "release 2.0"})
    assert r.status_code == 201
    new_id = r.json()["id"]
    vers = c.get(f"/api/v1/configs/{new_id}/versions").json()["versions"]
    assert len(vers) == 1
    assert vers[0]["note"] == "release 2.0"
    assert vers[0]["changed_by"] == "deploy-bot"


def test_promote_to_existing_environment_returns_409(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="app.timeout", environment="production")
    d = _create(c, key="app.timeout", environment="staging")
    r = c.post(f"/api/v1/configs/{d['id']}/promote",
               json={"target_environment": "production"})
    assert r.status_code == 409


def test_promote_nonexistent_config_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/configs/no-id/promote",
               json={"target_environment": "production"})
    assert r.status_code == 404


# ── Cascade delete ────────────────────────────────────────────────────────────

def test_delete_cascades_versions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, value="v1")
    cfg_id = d["id"]
    _patch(c, cfg_id, value="v2")
    _patch(c, cfg_id, value="v3")
    c.delete(f"/api/v1/configs/{cfg_id}")
    con = sqlite3.connect(cm_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM config_versions WHERE config_id=?", (cfg_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/configs/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["active"] == 0
    assert s["deprecated"] == 0
    assert s["total_versions"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, key="a", environment="production")
    d2 = _create(c, key="b", environment="staging")
    _transition(c, d1["id"], "deprecated")
    s = c.get("/api/v1/configs/stats").json()
    assert s["total"] == 2
    assert s["active"] == 1
    assert s["deprecated"] == 1


def test_stats_total_versions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, value="v0")
    _patch(c, d["id"], value="v1")
    _patch(c, d["id"], value="v2")
    s = c.get("/api/v1/configs/stats").json()
    assert s["total_versions"] == 3


def test_stats_by_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="a", environment="production")
    _create(c, key="b", environment="production")
    _create(c, key="c", environment="staging")
    s = c.get("/api/v1/configs/stats").json()
    envs = {row["environment"]: row["count"] for row in s["by_environment"]}
    assert envs["production"] == 2
    assert envs["staging"] == 1


def test_stats_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, key="a", type="string", environment="production")
    _create(c, key="b", type="string", environment="staging")
    _create(c, key="c", type="number", environment="dev")
    s = c.get("/api/v1/configs/stats").json()
    types = {row["type"]: row["count"] for row in s["by_type"]}
    assert types["string"] == 2
    assert types["number"] == 1
