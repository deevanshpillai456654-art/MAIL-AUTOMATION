"""Tests for backend/api/service_catalog.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.service_catalog as sc_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "sc_test.db")
    monkeypatch.setattr(sc_mod, "_DB_PATH", db_path)
    sc_mod._init_db()

    app = FastAPI()
    app.include_router(sc_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "Test Service", "tier": "tier3", **kwargs}
    r = c.post("/api/v1/services", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Payment API", tier="tier1", owner="payments-team")
    svc_id = d["id"]
    assert d["status"] == "operational"

    r = c.get(f"/api/v1/services/{svc_id}")
    assert r.status_code == 200
    s = r.json()
    assert s["name"] == "Payment API"
    assert s["tier"] == "tier1"
    assert s["owner"] == "payments-team"
    assert s["status"] == "operational"
    assert s["slug"] == "payment-api"


def test_get_by_slug(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Auth Service")
    r = c.get("/api/v1/services/auth-service")
    assert r.status_code == 200
    assert r.json()["name"] == "Auth Service"


def test_slug_uniqueness(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="My Service")
    d2 = _create(c, name="My Service")
    assert d1["slug"] != d2["slug"]
    assert d2["slug"].startswith("my-service")


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Alpha")
    _create(c, name="Beta")
    r = c.get("/api/v1/services")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    names = {s["name"] for s in d["services"]}
    assert "Alpha" in names and "Beta" in names


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="Healthy")
    d2 = _create(c, name="Broken")
    c.post(f"/api/v1/services/{d2['id']}/status", json={"status": "major_outage"})
    r = c.get("/api/v1/services?status=major_outage")
    assert r.json()["total"] == 1
    assert r.json()["services"][0]["id"] == d2["id"]


def test_list_filter_by_tier(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Critical", tier="tier1")
    _create(c, name="Standard", tier="tier3")
    r = c.get("/api/v1/services?tier=tier1")
    assert r.json()["total"] == 1
    assert r.json()["services"][0]["tier"] == "tier1"


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Notification Engine", owner="messaging-team")
    _create(c, name="Billing Service")
    r = c.get("/api/v1/services?q=billing")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(6):
        _create(c, name=f"Service {i}")
    r = c.get("/api/v1/services?limit=4&offset=0")
    assert len(r.json()["services"]) == 4
    assert r.json()["total"] == 6
    r2 = c.get("/api/v1/services?limit=4&offset=4")
    assert len(r2.json()["services"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Old Name")
    r = c.patch(f"/api/v1/services/{d['id']}", json={
        "name": "New Name", "tier": "tier1", "team": "platform-team"
    })
    assert r.status_code == 200
    s = c.get(f"/api/v1/services/{d['id']}").json()
    assert s["name"] == "New Name"
    assert s["tier"] == "tier1"
    assert s["team"] == "platform-team"
    assert s["slug"] == "new-name"


def test_patch_invalid_tier_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.patch(f"/api/v1/services/{d['id']}", json={"tier": "tier99"})
    assert r.status_code == 400


def test_delete_removes_service(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/services/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/services/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/services/no-such-id").status_code == 404


def test_invalid_status_on_create_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/services", json={"name": "X", "status": "on_fire"})
    assert r.status_code == 400


def test_invalid_tier_on_create_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/services", json={"name": "X", "tier": "tierX"})
    assert r.status_code == 400


# ── Status updates ────────────────────────────────────────────────────────────

def test_update_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/services/{d['id']}/status", json={
        "status": "degraded", "reason": "High latency", "author": "ops-bot"
    })
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    s = c.get(f"/api/v1/services/{d['id']}").json()
    assert s["status"] == "degraded"


def test_update_status_all_valid_values(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    for st in ("degraded", "partial_outage", "major_outage", "maintenance", "deprecated", "operational"):
        r = c.post(f"/api/v1/services/{d['id']}/status", json={"status": st})
        assert r.status_code == 200


def test_update_status_invalid_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/services/{d['id']}/status", json={"status": "catastrophic"})
    assert r.status_code == 400


def test_update_status_nonexistent_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/services/no-id/status", json={"status": "degraded"})
    assert r.status_code == 404


# ── History ───────────────────────────────────────────────────────────────────

def test_history_seeded_on_create(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Alpha", status="operational")
    r = c.get(f"/api/v1/services/{d['id']}/history")
    assert r.status_code == 200
    h = r.json()["history"]
    assert len(h) >= 1
    assert h[0]["new_status"] == "operational"


def test_history_records_transitions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    c.post(f"/api/v1/services/{d['id']}/status", json={"status": "degraded", "reason": "DB slow"})
    c.post(f"/api/v1/services/{d['id']}/status", json={"status": "operational", "reason": "Fixed"})
    r = c.get(f"/api/v1/services/{d['id']}/history")
    h = r.json()["history"]
    statuses = [e["new_status"] for e in h]
    assert "degraded" in statuses
    assert "operational" in statuses


def test_history_records_previous_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    c.post(f"/api/v1/services/{d['id']}/status", json={"status": "degraded"})
    r = c.get(f"/api/v1/services/{d['id']}/history")
    h = r.json()["history"]
    degraded_entry = next(e for e in h if e["new_status"] == "degraded")
    assert degraded_entry["previous_status"] == "operational"


def test_history_total_count(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    for st in ("degraded", "major_outage", "maintenance", "operational"):
        c.post(f"/api/v1/services/{d['id']}/status", json={"status": st})
    r = c.get(f"/api/v1/services/{d['id']}/history")
    assert r.json()["total"] >= 5  # 1 seed + 4 updates


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/services/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_stats_totals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", tier="tier1")
    _create(c, name="B", tier="tier1")
    _create(c, name="C", tier="tier3")
    r = c.get("/api/v1/services/stats")
    d = r.json()
    assert d["total"] == 3
    by_tier = {x["tier"]: x["count"] for x in d["by_tier"]}
    assert by_tier.get("tier1", 0) == 2
    assert by_tier.get("tier3", 0) == 1


def test_stats_degraded_count(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="Good")
    d2 = _create(c, name="Bad")
    c.post(f"/api/v1/services/{d2['id']}/status", json={"status": "degraded"})
    r = c.get("/api/v1/services/stats")
    assert r.json()["degraded"] == 1


# ── Cascade delete ────────────────────────────────────────────────────────────

def test_delete_cascades_history(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    svc_id = d["id"]
    c.post(f"/api/v1/services/{svc_id}/status", json={"status": "degraded"})
    c.delete(f"/api/v1/services/{svc_id}")
    con = sqlite3.connect(sc_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM service_status_history WHERE service_id=?", (svc_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0
