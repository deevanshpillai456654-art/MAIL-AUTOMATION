"""Tests for backend/api/capacity_planning.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.capacity_planning as cap_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cap_test.db")
    monkeypatch.setattr(cap_mod, "_DB_PATH", db_path)
    cap_mod._init_db()

    app = FastAPI()
    app.include_router(cap_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "prod-cpu-pool", "type": "cpu", "unit": "vCPU",
               "total_capacity": 100.0, **kwargs}
    r = c.post("/api/v1/capacity/resources", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, res_id, status, **kwargs):
    return c.post(f"/api/v1/capacity/resources/{res_id}/transition",
                  json={"status": status, **kwargs})


def _snapshot(c, res_id, used, total, **kwargs):
    return c.post(f"/api/v1/capacity/resources/{res_id}/snapshots",
                  json={"used": used, "total": total, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="mem-pool", type="memory", unit="GB",
                total_capacity=512.0, allocated_capacity=256.0,
                environment="production", owner="infra-team")
    res_id = d["id"]
    assert d["status"] == "active"

    r = c.get(f"/api/v1/capacity/resources/{res_id}")
    assert r.status_code == 200
    res = r.json()
    assert res["name"] == "mem-pool"
    assert res["type"] == "memory"
    assert res["unit"] == "GB"
    assert res["total_capacity"] == 512.0
    assert res["allocated_capacity"] == 256.0
    assert res["environment"] == "production"
    assert res["status"] == "active"


def test_default_status_is_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    assert d["status"] == "active"


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="alpha-pool")
    _create(c, name="beta-pool")
    r = c.get("/api/v1/capacity/resources")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_filter_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="cpu-pool", type="cpu")
    _create(c, name="mem-pool", type="memory")
    r = c.get("/api/v1/capacity/resources?type=cpu")
    assert r.json()["total"] == 1
    assert r.json()["resources"][0]["type"] == "cpu"


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "warning")
    r = c.get("/api/v1/capacity/resources?status=warning")
    assert r.json()["total"] == 1
    assert r.json()["resources"][0]["id"] == d1["id"]


def test_list_filter_by_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="prod", environment="production")
    _create(c, name="stg", environment="staging")
    r = c.get("/api/v1/capacity/resources?environment=staging")
    assert r.json()["total"] == 1


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="database-cluster", owner="dba-team")
    _create(c, name="web-pool", owner="app-team")
    r = c.get("/api/v1/capacity/resources?q=database")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"pool-{i}")
    r = c.get("/api/v1/capacity/resources?limit=3&offset=0")
    assert len(r.json()["resources"]) == 3
    r2 = c.get("/api/v1/capacity/resources?limit=3&offset=3")
    assert len(r2.json()["resources"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="old-name")
    r = c.patch(f"/api/v1/capacity/resources/{d['id']}", json={
        "name": "new-name", "total_capacity": 200.0, "owner": "ops"
    })
    assert r.status_code == 200
    res = c.get(f"/api/v1/capacity/resources/{d['id']}").json()
    assert res["name"] == "new-name"
    assert res["total_capacity"] == 200.0
    assert res["owner"] == "ops"


def test_patch_invalid_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.patch(f"/api/v1/capacity/resources/{d['id']}", json={"type": "spaceship"})
    assert r.status_code == 400


def test_delete_removes_resource(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/capacity/resources/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/capacity/resources/no-id").status_code == 404


def test_create_invalid_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/capacity/resources", json={"name": "bad", "type": "laser"})
    assert r.status_code == 400


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_active_to_warning(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "warning")
    assert r.status_code == 200
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "warning"


def test_transition_active_to_critical(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "critical")
    assert r.status_code == 200
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "critical"


def test_transition_warning_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "warning")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_transition_critical_to_warning(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "critical")
    r = _transition(c, d["id"], "warning")
    assert r.status_code == 200


def test_transition_to_decommissioned(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "decommissioned")
    assert r.status_code == 200
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "decommissioned"


def test_decommissioned_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "decommissioned")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "decommissioned")
    assert r.status_code == 200
    r2 = _transition(c, d["id"], "warning")
    assert r2.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "exploded")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "warning")
    assert r.status_code == 404


# ── Snapshots ─────────────────────────────────────────────────────────────────

def test_add_and_list_snapshot(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _snapshot(c, d["id"], used=60.0, total=100.0)
    assert r.status_code == 201
    assert r.json()["utilization_pct"] == 60.0

    snaps = c.get(f"/api/v1/capacity/resources/{d['id']}/snapshots").json()["snapshots"]
    assert len(snaps) == 1
    assert snaps[0]["used"] == 60.0
    assert snaps[0]["utilization_pct"] == 60.0


def test_snapshot_utilization_pct_computed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _snapshot(c, d["id"], used=33.0, total=200.0)
    assert r.json()["utilization_pct"] == 16.5


def test_snapshot_zero_total_gives_zero_pct(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _snapshot(c, d["id"], used=0.0, total=0.0)
    assert r.status_code == 201
    assert r.json()["utilization_pct"] == 0.0


def test_snapshot_auto_escalates_to_warning(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _snapshot(c, d["id"], used=80.0, total=100.0)
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "warning"


def test_snapshot_auto_escalates_to_critical(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _snapshot(c, d["id"], used=95.0, total=100.0)
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "critical"


def test_snapshot_auto_drops_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _snapshot(c, d["id"], used=95.0, total=100.0)
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "critical"
    _snapshot(c, d["id"], used=50.0, total=100.0)
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "active"


def test_snapshot_does_not_change_decommissioned_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "decommissioned")
    _snapshot(c, d["id"], used=99.0, total=100.0)
    assert c.get(f"/api/v1/capacity/resources/{d['id']}").json()["status"] == "decommissioned"


def test_snapshot_on_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _snapshot(c, "no-id", used=10.0, total=100.0)
    assert r.status_code == 404


def test_global_recent_snapshots(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="pool-A")
    d2 = _create(c, name="pool-B")
    _snapshot(c, d1["id"], 10, 100)
    _snapshot(c, d2["id"], 20, 100)
    r = c.get("/api/v1/capacity/snapshots")
    assert r.status_code == 200
    assert len(r.json()["snapshots"]) == 2


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/capacity/resources/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["critical"] == 0
    assert s["warning"] == 0


def test_stats_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    d2 = _create(c, name="B")
    _create(c, name="C")
    _snapshot(c, d1["id"], 95, 100)
    _snapshot(c, d2["id"], 80, 100)
    r = c.get("/api/v1/capacity/resources/stats")
    s = r.json()
    assert s["critical"] == 1
    assert s["warning"] == 1


def test_stats_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", type="cpu")
    _create(c, name="B", type="cpu")
    _create(c, name="C", type="storage")
    r = c.get("/api/v1/capacity/resources/stats")
    by_type = {x["type"]: x["count"] for x in r.json()["by_type"]}
    assert by_type.get("cpu", 0) == 2
    assert by_type.get("storage", 0) == 1


# ── Cascade delete ─────────────────────────────────────────────────────────────

def test_delete_cascades_snapshots(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    res_id = d["id"]
    _snapshot(c, res_id, 50, 100)
    _snapshot(c, res_id, 60, 100)
    c.delete(f"/api/v1/capacity/resources/{res_id}")
    con = sqlite3.connect(cap_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM capacity_snapshots WHERE resource_id=?", (res_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0
