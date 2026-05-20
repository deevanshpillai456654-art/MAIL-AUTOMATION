"""Tests for backend/api/feature_flags.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.feature_flags as ff_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ff_test.db")
    monkeypatch.setattr(ff_mod, "_DB_PATH", db_path)
    ff_mod._init_db()

    app = FastAPI()
    app.include_router(ff_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "new checkout flow", **kwargs}
    r = c.post("/api/v1/flags", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, flag_id, status, **kwargs):
    return c.post(f"/api/v1/flags/{flag_id}/transition",
                  json={"status": status, **kwargs})


def _set_env(c, flag_id, environment, enabled=True, rollout_pct=100.0, **kwargs):
    return c.post(f"/api/v1/flags/{flag_id}/environments", json={
        "environment": environment, "enabled": enabled,
        "rollout_pct": rollout_pct, **kwargs
    })


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Dark Mode Toggle", description="Enables dark mode UI",
                owner="frontend-team", tags="ui,experiment")
    flag_id = d["id"]
    assert d["status"] == "draft"
    assert d["key"]

    r = c.get(f"/api/v1/flags/{flag_id}")
    assert r.status_code == 200
    f = r.json()
    assert f["name"] == "Dark Mode Toggle"
    assert f["description"] == "Enables dark mode UI"
    assert f["owner"] == "frontend-team"
    assert f["status"] == "draft"


def test_key_auto_generated_snake_case(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="New Checkout Flow")
    assert d["key"] == "new_checkout_flow"


def test_key_dedup_on_collision(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="Same Name")
    d2 = _create(c, name="Same Name")
    assert d1["key"] != d2["key"]
    assert d2["key"].startswith("same_name")


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Flag A")
    _create(c, name="Flag B")
    r = c.get("/api/v1/flags")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "active")
    r = c.get("/api/v1/flags?status=active")
    assert r.json()["total"] == 1
    assert r.json()["flags"][0]["id"] == d1["id"]


def test_list_search_name(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="payment redesign", tags="checkout")
    _create(c, name="dark mode", tags="ui")
    r = c.get("/api/v1/flags?q=payment")
    assert r.json()["total"] == 1


def test_list_search_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Turbo Mode")
    _create(c, name="Slow Mode")
    r = c.get("/api/v1/flags?q=turbo_mode")
    assert r.json()["total"] == 1


def test_list_search_tags(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", tags="experiment,beta")
    _create(c, name="B", tags="stable")
    r = c.get("/api/v1/flags?q=experiment")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"Flag {i}")
    r = c.get("/api/v1/flags?limit=3&offset=0")
    assert len(r.json()["flags"]) == 3
    r2 = c.get("/api/v1/flags?limit=3&offset=3")
    assert len(r2.json()["flags"]) == 2


def test_patch_updates_metadata(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Old Name")
    r = c.patch(f"/api/v1/flags/{d['id']}", json={
        "description": "Updated desc", "owner": "new-team", "tags": "a,b"
    })
    assert r.status_code == 200
    f = c.get(f"/api/v1/flags/{d['id']}").json()
    assert f["description"] == "Updated desc"
    assert f["owner"] == "new-team"


def test_patch_name_updates_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Old Name")
    c.patch(f"/api/v1/flags/{d['id']}", json={"name": "Brand New Name"})
    f = c.get(f"/api/v1/flags/{d['id']}").json()
    assert f["key"] == "brand_new_name"


def test_delete_removes_flag(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/flags/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/flags/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/flags/no-id").status_code == 404


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_draft_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200
    assert c.get(f"/api/v1/flags/{d['id']}").json()["status"] == "active"


def test_transition_active_to_deprecated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "deprecated")
    assert r.status_code == 200


def test_transition_deprecated_back_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "deprecated")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_transition_draft_to_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "archived")
    assert r.status_code == 200


def test_transition_active_to_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "archived")
    assert r.status_code == 200
    assert c.get(f"/api/v1/flags/{d['id']}").json()["status"] == "archived"


def test_archived_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "archived")
    r = _transition(c, d["id"], "draft")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "deprecated")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "launched")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "active")
    assert r.status_code == 404


# ── Environments ──────────────────────────────────────────────────────────────

def test_set_and_get_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _set_env(c, d["id"], "production", enabled=True, rollout_pct=50.0)
    assert r.status_code in (200, 201)
    envs = c.get(f"/api/v1/flags/{d['id']}/environments").json()["environments"]
    assert len(envs) == 1
    assert envs[0]["environment"] == "production"
    assert envs[0]["enabled"] == 1
    assert envs[0]["rollout_pct"] == 50.0


def test_upsert_updates_existing_env(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _set_env(c, d["id"], "staging", enabled=False, rollout_pct=0.0)
    _set_env(c, d["id"], "staging", enabled=True,  rollout_pct=75.0)
    envs = c.get(f"/api/v1/flags/{d['id']}/environments").json()["environments"]
    assert len(envs) == 1
    assert envs[0]["enabled"] == 1
    assert envs[0]["rollout_pct"] == 75.0


def test_multiple_environments(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _set_env(c, d["id"], "production", enabled=True,  rollout_pct=100.0)
    _set_env(c, d["id"], "staging",    enabled=True,  rollout_pct=50.0)
    _set_env(c, d["id"], "dev",        enabled=False, rollout_pct=0.0)
    envs = c.get(f"/api/v1/flags/{d['id']}/environments").json()["environments"]
    assert len(envs) == 3


def test_rollout_pct_above_100_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _set_env(c, d["id"], "production", enabled=True, rollout_pct=101.0)
    assert r.status_code == 422


def test_rollout_pct_negative_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _set_env(c, d["id"], "production", enabled=True, rollout_pct=-1.0)
    assert r.status_code == 422


def test_env_on_nonexistent_flag_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _set_env(c, "no-id", "production")
    assert r.status_code == 404


def test_evaluate_active_flag_enabled_for_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Runtime Controls")
    _transition(c, d["id"], "active")
    _set_env(c, d["id"], "production", enabled=True, rollout_pct=100.0)

    r = c.get("/api/v1/flags/evaluate/runtime_controls?environment=production&tenant_id=tenant-a")

    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["key"] == "runtime_controls"
    assert body["reason"] == "enabled"


def test_evaluate_draft_flag_is_disabled(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Draft Feature")
    _set_env(c, d["id"], "production", enabled=True, rollout_pct=100.0)

    r = c.get("/api/v1/flags/evaluate/draft_feature?environment=production&tenant_id=tenant-a")

    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["reason"] == "flag_not_active"


def test_evaluate_rollout_is_deterministic_for_tenant(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Gradual Feature")
    _transition(c, d["id"], "active")
    _set_env(c, d["id"], "production", enabled=True, rollout_pct=25.0)

    first = c.get("/api/v1/flags/evaluate/gradual_feature?environment=production&tenant_id=tenant-a").json()
    second = c.get("/api/v1/flags/evaluate/gradual_feature?environment=production&tenant_id=tenant-a").json()

    assert first["enabled"] == second["enabled"]
    assert first["bucket"] == second["bucket"]
    assert 1 <= first["bucket"] <= 100


# ── Events ────────────────────────────────────────────────────────────────────

def test_event_seeded_on_create(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    evts = c.get(f"/api/v1/flags/{d['id']}/events").json()["events"]
    assert len(evts) >= 1
    assert any(e["event_type"] == "created" for e in evts)


def test_status_change_event_on_transition(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active", author="ci-bot")
    evts = c.get(f"/api/v1/flags/{d['id']}/events").json()["events"]
    assert any(e["event_type"] == "status_changed" for e in evts)


def test_env_change_logs_event(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _set_env(c, d["id"], "production", enabled=True)
    evts = c.get(f"/api/v1/flags/{d['id']}/events").json()["events"]
    assert any(e["event_type"] == "enabled" for e in evts)


def test_add_manual_event(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/flags/{d['id']}/events", json={
        "event_type": "note", "note": "Reviewed by QA", "author": "qa-team"
    })
    assert r.status_code == 201
    evts = c.get(f"/api/v1/flags/{d['id']}/events").json()["events"]
    assert any(e["note"] == "Reviewed by QA" for e in evts)


def test_invalid_event_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/flags/{d['id']}/events",
               json={"event_type": "explosion", "note": "boom"})
    assert r.status_code == 400


def test_event_on_nonexistent_flag_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/flags/no-id/events", json={"note": "X"})
    assert r.status_code == 404


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/flags/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["active"] == 0
    assert s["enabled_envs"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    d2 = _create(c, name="B")
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")
    r = c.get("/api/v1/flags/stats")
    assert r.json()["active"] == 2


def test_stats_enabled_envs(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _set_env(c, d["id"], "production", enabled=True)
    _set_env(c, d["id"], "staging",    enabled=False)
    r = c.get("/api/v1/flags/stats")
    assert r.json()["enabled_envs"] == 1
    assert r.json()["total_envs"] == 2


# ── Cascade delete ─────────────────────────────────────────────────────────────

def test_delete_cascades_envs_and_events(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    flag_id = d["id"]
    _set_env(c, flag_id, "production", enabled=True)
    c.delete(f"/api/v1/flags/{flag_id}")
    con = sqlite3.connect(ff_mod._DB_PATH)
    env_count = con.execute(
        "SELECT COUNT(*) FROM flag_environments WHERE flag_id=?", (flag_id,)
    ).fetchone()[0]
    evt_count = con.execute(
        "SELECT COUNT(*) FROM flag_events WHERE flag_id=?", (flag_id,)
    ).fetchone()[0]
    con.close()
    assert env_count == 0
    assert evt_count == 0
