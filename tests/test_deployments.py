"""Tests for backend/api/deployments.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.deployments as dep_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "dep_test.db")
    monkeypatch.setattr(dep_mod, "_DB_PATH", db_path)
    dep_mod._init_db()

    app = FastAPI()
    app.include_router(dep_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "api-service v1.0", "environment": "production", **kwargs}
    r = c.post("/api/v1/deployments", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, dep_id, status, **kwargs):
    return c.post(f"/api/v1/deployments/{dep_id}/transition",
                  json={"status": status, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="payment-api", version="2.4.1", environment="staging",
                deployer="ci-bot", service_id="svc-123")
    dep_id = d["id"]
    assert d["status"] == "planned"

    r = c.get(f"/api/v1/deployments/{dep_id}")
    assert r.status_code == 200
    dep = r.json()
    assert dep["name"] == "payment-api"
    assert dep["version"] == "2.4.1"
    assert dep["environment"] == "staging"
    assert dep["deployer"] == "ci-bot"
    assert dep["status"] == "planned"
    assert dep["started_at"] is None
    assert dep["finished_at"] is None
    assert dep["rollback_at"] is None


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="alpha")
    _create(c, name="beta")
    r = c.get("/api/v1/deployments")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    names = {dep["name"] for dep in d["deployments"]}
    assert "alpha" in names and "beta" in names


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "in_progress")
    r = c.get("/api/v1/deployments?status=in_progress")
    assert r.json()["total"] == 1
    assert r.json()["deployments"][0]["id"] == d1["id"]


def test_list_filter_by_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="prod-one", environment="production")
    _create(c, name="stg-one", environment="staging")
    r = c.get("/api/v1/deployments?environment=staging")
    assert r.json()["total"] == 1
    assert r.json()["deployments"][0]["environment"] == "staging"


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="payment-service", deployer="alice")
    _create(c, name="auth-service", deployer="bob")
    r = c.get("/api/v1/deployments?q=payment")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"deploy-{i}")
    r = c.get("/api/v1/deployments?limit=3&offset=0")
    assert len(r.json()["deployments"]) == 3
    r2 = c.get("/api/v1/deployments?limit=3&offset=3")
    assert len(r2.json()["deployments"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="old-name")
    r = c.patch(f"/api/v1/deployments/{d['id']}", json={
        "name": "new-name", "version": "3.0.0", "deployer": "alice"
    })
    assert r.status_code == 200
    dep = c.get(f"/api/v1/deployments/{d['id']}").json()
    assert dep["name"] == "new-name"
    assert dep["version"] == "3.0.0"
    assert dep["deployer"] == "alice"


def test_delete_removes_deployment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/deployments/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/deployments/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/deployments/no-such-id").status_code == 404


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_planned_to_in_progress(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "in_progress")
    assert r.status_code == 200
    dep = c.get(f"/api/v1/deployments/{d['id']}").json()
    assert dep["status"] == "in_progress"
    assert dep["started_at"] is not None


def test_transition_to_success_sets_finished_at(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "in_progress")
    _transition(c, d["id"], "success")
    dep = c.get(f"/api/v1/deployments/{d['id']}").json()
    assert dep["status"] == "success"
    assert dep["finished_at"] is not None


def test_transition_to_failed_sets_finished_at(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "in_progress")
    _transition(c, d["id"], "failed")
    dep = c.get(f"/api/v1/deployments/{d['id']}").json()
    assert dep["status"] == "failed"
    assert dep["finished_at"] is not None


def test_transition_failed_to_rolled_back(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "in_progress")
    _transition(c, d["id"], "failed")
    r = _transition(c, d["id"], "rolled_back")
    assert r.status_code == 200
    dep = c.get(f"/api/v1/deployments/{d['id']}").json()
    assert dep["status"] == "rolled_back"
    assert dep["rollback_at"] is not None


def test_transition_success_to_rolled_back(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "in_progress")
    _transition(c, d["id"], "success")
    r = _transition(c, d["id"], "rolled_back")
    assert r.status_code == 200
    dep = c.get(f"/api/v1/deployments/{d['id']}").json()
    assert dep["rollback_at"] is not None


def test_planned_to_cancelled(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "cancelled")
    assert r.status_code == 200
    dep = c.get(f"/api/v1/deployments/{d['id']}").json()
    assert dep["status"] == "cancelled"
    assert dep["finished_at"] is not None


def test_rolled_back_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "in_progress")
    _transition(c, d["id"], "failed")
    _transition(c, d["id"], "rolled_back")
    r = _transition(c, d["id"], "planned")
    assert r.status_code == 400


def test_cancelled_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "cancelled")
    r = _transition(c, d["id"], "in_progress")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "success")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "exploded")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "in_progress")
    assert r.status_code == 404


# ── Notes ──────────────────────────────────────────────────────────────────────

def test_notes_seeded_on_create(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.get(f"/api/v1/deployments/{d['id']}/notes")
    assert r.status_code == 200
    notes = r.json()["notes"]
    assert len(notes) >= 1


def test_add_note(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/deployments/{d['id']}/notes", json={
        "note": "Canary metrics look healthy", "author": "alice"
    })
    assert r.status_code == 201
    notes = c.get(f"/api/v1/deployments/{d['id']}/notes").json()["notes"]
    assert any(n["note"] == "Canary metrics look healthy" for n in notes)


def test_notes_on_transition(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "in_progress", note="Starting rollout", author="ci-bot")
    notes = c.get(f"/api/v1/deployments/{d['id']}/notes").json()["notes"]
    assert any("Starting rollout" in n["note"] for n in notes)


def test_note_on_nonexistent_deployment_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/deployments/no-id/notes", json={"note": "X"})
    assert r.status_code == 404


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/deployments/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_stats_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c)
    d2 = _create(c)
    _transition(c, d1["id"], "in_progress")
    _transition(c, d1["id"], "success")
    _transition(c, d2["id"], "in_progress")
    _transition(c, d2["id"], "failed")
    r = c.get("/api/v1/deployments/stats")
    by_status = {x["status"]: x["count"] for x in r.json()["by_status"]}
    assert by_status.get("success", 0) == 1
    assert by_status.get("failed", 0) == 1


def test_stats_by_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, environment="production")
    _create(c, environment="production")
    _create(c, environment="staging")
    r = c.get("/api/v1/deployments/stats")
    by_env = {x["environment"]: x["count"] for x in r.json()["by_env"]}
    assert by_env.get("production", 0) == 2
    assert by_env.get("staging", 0) == 1


# ── Cascade delete ────────────────────────────────────────────────────────────

def test_delete_cascades_notes(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    dep_id = d["id"]
    c.post(f"/api/v1/deployments/{dep_id}/notes", json={"note": "test note"})
    c.delete(f"/api/v1/deployments/{dep_id}")
    con = sqlite3.connect(dep_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM deployment_notes WHERE deployment_id=?", (dep_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0
