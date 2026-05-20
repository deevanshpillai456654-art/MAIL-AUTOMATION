"""Tests for backend/api/asset_management.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.asset_management as am_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "am_test.db")
    monkeypatch.setattr(am_mod, "_DB_PATH", db_path)
    am_mod._init_db()

    app = FastAPI()
    app.include_router(am_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "web-server-01", **kwargs}
    r = c.post("/api/v1/assets", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, asset_id, status, **kwargs):
    return c.post(f"/api/v1/assets/{asset_id}/transition",
                  json={"status": status, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="db-primary", type="database", environment="production",
                owner="dba-team", hostname="db01.prod", ip_address="10.0.0.1")
    asset_id = d["id"]
    assert d["status"] == "discovered"

    r = c.get(f"/api/v1/assets/{asset_id}")
    assert r.status_code == 200
    a = r.json()
    assert a["name"] == "db-primary"
    assert a["type"] == "database"
    assert a["environment"] == "production"
    assert a["owner"] == "dba-team"
    assert a["hostname"] == "db01.prod"
    assert a["ip_address"] == "10.0.0.1"
    assert a["status"] == "discovered"


def test_default_type_is_other(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="mystery-ci")
    assert d["status"] == "discovered"
    a = c.get(f"/api/v1/assets/{d['id']}").json()
    assert a["type"] == "other"


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="alpha")
    _create(c, name="beta")
    r = c.get("/api/v1/assets")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    names = {a["name"] for a in data["assets"]}
    assert "alpha" in names and "beta" in names


def test_list_filter_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="srv", type="server")
    _create(c, name="app", type="application")
    r = c.get("/api/v1/assets?type=server")
    assert r.json()["total"] == 1
    assert r.json()["assets"][0]["type"] == "server"


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "active")
    r = c.get("/api/v1/assets?status=active")
    assert r.json()["total"] == 1
    assert r.json()["assets"][0]["id"] == d1["id"]


def test_list_filter_by_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="prod-server", environment="production")
    _create(c, name="stg-server", environment="staging")
    r = c.get("/api/v1/assets?environment=staging")
    assert r.json()["total"] == 1
    assert r.json()["assets"][0]["environment"] == "staging"


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="postgres-primary", hostname="pg01.prod", tags="database,primary")
    _create(c, name="nginx-lb", hostname="lb01.prod")
    r = c.get("/api/v1/assets?q=postgres")
    assert r.json()["total"] == 1


def test_list_search_by_tags(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="srv-a", tags="critical,production")
    _create(c, name="srv-b", tags="dev")
    r = c.get("/api/v1/assets?q=critical")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"asset-{i}")
    r = c.get("/api/v1/assets?limit=3&offset=0")
    assert len(r.json()["assets"]) == 3
    r2 = c.get("/api/v1/assets?limit=3&offset=3")
    assert len(r2.json()["assets"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="old-name")
    r = c.patch(f"/api/v1/assets/{d['id']}", json={
        "name": "new-name", "hostname": "new-host", "version": "2.0"
    })
    assert r.status_code == 200
    a = c.get(f"/api/v1/assets/{d['id']}").json()
    assert a["name"] == "new-name"
    assert a["hostname"] == "new-host"
    assert a["version"] == "2.0"


def test_patch_invalid_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.patch(f"/api/v1/assets/{d['id']}", json={"type": "spaceship"})
    assert r.status_code == 400


def test_delete_removes_asset(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/assets/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/assets/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/assets/no-such-id").status_code == 404


def test_create_invalid_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/assets", json={"name": "bad", "type": "unicorn"})
    assert r.status_code == 400


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_discovered_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200
    assert c.get(f"/api/v1/assets/{d['id']}").json()["status"] == "active"


def test_transition_active_to_maintenance(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "maintenance")
    assert r.status_code == 200
    assert c.get(f"/api/v1/assets/{d['id']}").json()["status"] == "maintenance"


def test_transition_maintenance_back_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "maintenance")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200
    assert c.get(f"/api/v1/assets/{d['id']}").json()["status"] == "active"


def test_transition_active_to_deprecated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "deprecated")
    assert r.status_code == 200


def test_transition_deprecated_to_retired(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "deprecated")
    r = _transition(c, d["id"], "retired")
    assert r.status_code == 200
    assert c.get(f"/api/v1/assets/{d['id']}").json()["status"] == "retired"


def test_transition_discovered_to_retired(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "retired")
    assert r.status_code == 200


def test_retired_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "retired")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "maintenance")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "vaporized")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "active")
    assert r.status_code == 404


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/assets/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["active"] == 0


def test_stats_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c)
    d2 = _create(c)
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "retired")
    r = c.get("/api/v1/assets/stats")
    by_status = {x["status"]: x["count"] for x in r.json()["by_status"]}
    assert by_status.get("active", 0) == 1
    assert by_status.get("retired", 0) == 1


def test_stats_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, type="server")
    _create(c, type="server")
    _create(c, type="database")
    r = c.get("/api/v1/assets/stats")
    by_type = {x["type"]: x["count"] for x in r.json()["by_type"]}
    assert by_type.get("server", 0) == 2
    assert by_type.get("database", 0) == 1


def test_stats_active_count(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c)
    d2 = _create(c)
    _create(c)
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")
    r = c.get("/api/v1/assets/stats")
    assert r.json()["active"] == 2


# ── Relationships ──────────────────────────────────────────────────────────────

def test_add_and_list_relationship(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="app-server")
    a2 = _create(c, name="db-server")
    r = c.post(f"/api/v1/assets/{a1['id']}/relationships", json={
        "target_id": a2["id"], "relation_type": "depends_on"
    })
    assert r.status_code == 201
    rels = c.get(f"/api/v1/assets/{a1['id']}/relationships").json()["relationships"]
    assert len(rels) == 1
    assert rels[0]["relation_type"] == "depends_on"


def test_relationship_visible_from_target(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="app")
    a2 = _create(c, name="db")
    c.post(f"/api/v1/assets/{a1['id']}/relationships", json={
        "target_id": a2["id"], "relation_type": "depends_on"
    })
    rels = c.get(f"/api/v1/assets/{a2['id']}/relationships").json()["relationships"]
    assert len(rels) == 1


def test_duplicate_relationship_returns_409(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="a")
    a2 = _create(c, name="b")
    c.post(f"/api/v1/assets/{a1['id']}/relationships",
           json={"target_id": a2["id"], "relation_type": "hosts"})
    r = c.post(f"/api/v1/assets/{a1['id']}/relationships",
               json={"target_id": a2["id"], "relation_type": "hosts"})
    assert r.status_code == 409


def test_invalid_relation_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="a")
    a2 = _create(c, name="b")
    r = c.post(f"/api/v1/assets/{a1['id']}/relationships",
               json={"target_id": a2["id"], "relation_type": "destroys"})
    assert r.status_code == 400


def test_target_not_found_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="a")
    r = c.post(f"/api/v1/assets/{a1['id']}/relationships",
               json={"target_id": "no-such-id", "relation_type": "hosts"})
    assert r.status_code == 404


def test_delete_relationship(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="a")
    a2 = _create(c, name="b")
    rel = c.post(f"/api/v1/assets/{a1['id']}/relationships",
                 json={"target_id": a2["id"], "relation_type": "hosts"}).json()
    r = c.delete(f"/api/v1/assets/{a1['id']}/relationships/{rel['id']}")
    assert r.status_code in (200, 204)
    rels = c.get(f"/api/v1/assets/{a1['id']}/relationships").json()["relationships"]
    assert len(rels) == 0


def test_delete_nonexistent_relationship_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a = _create(c, name="a")
    r = c.delete(f"/api/v1/assets/{a['id']}/relationships/no-rel-id")
    assert r.status_code == 404


# ── Events ────────────────────────────────────────────────────────────────────

def test_events_seeded_on_create(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    evts = c.get(f"/api/v1/assets/{d['id']}/events").json()["events"]
    assert len(evts) >= 1


def test_add_event(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/assets/{d['id']}/events", json={
        "event_type": "note", "note": "Reviewed config", "author": "ops-team"
    })
    assert r.status_code == 201
    evts = c.get(f"/api/v1/assets/{d['id']}/events").json()["events"]
    assert any(e["note"] == "Reviewed config" for e in evts)


def test_invalid_event_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/assets/{d['id']}/events",
               json={"event_type": "explosion", "note": "boom"})
    assert r.status_code == 400


def test_status_change_logged_on_transition(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active", note="Commissioned by ops")
    evts = c.get(f"/api/v1/assets/{d['id']}/events").json()["events"]
    assert any("Commissioned by ops" in e["note"] for e in evts)


def test_relationship_added_logged_on_rel_add(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="a")
    a2 = _create(c, name="b")
    c.post(f"/api/v1/assets/{a1['id']}/relationships",
           json={"target_id": a2["id"], "relation_type": "hosts"})
    evts = c.get(f"/api/v1/assets/{a1['id']}/events").json()["events"]
    assert any(e["event_type"] == "relationship_added" for e in evts)


def test_events_on_nonexistent_asset_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/assets/no-id/events", json={"note": "X"})
    assert r.status_code == 404


# ── Cascade delete ─────────────────────────────────────────────────────────────

def test_delete_cascades_relationships_and_events(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    a1 = _create(c, name="main")
    a2 = _create(c, name="dep")
    a1_id = a1["id"]
    c.post(f"/api/v1/assets/{a1_id}/relationships",
           json={"target_id": a2["id"], "relation_type": "depends_on"})
    c.delete(f"/api/v1/assets/{a1_id}")
    con = sqlite3.connect(am_mod._DB_PATH)
    rel_count = con.execute(
        "SELECT COUNT(*) FROM asset_relationships WHERE source_id=? OR target_id=?",
        (a1_id, a1_id),
    ).fetchone()[0]
    evt_count = con.execute(
        "SELECT COUNT(*) FROM asset_events WHERE asset_id=?", (a1_id,)
    ).fetchone()[0]
    con.close()
    assert rel_count == 0
    assert evt_count == 0
