"""Tests for backend/api/slo_management.py"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.slo_management as slo_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "slo_test.db")
    monkeypatch.setattr(slo_mod, "_DB_PATH", db_path)
    slo_mod._init_db()

    app = FastAPI()
    app.include_router(slo_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "API Availability", **kwargs}
    r = c.post("/api/v1/slos", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, slo_id, status, **kwargs):
    return c.post(f"/api/v1/slos/{slo_id}/transition",
                  json={"status": status, **kwargs})


def _measure(c, slo_id, actual_pct, **kwargs):
    return c.post(f"/api/v1/slos/{slo_id}/measurements",
                  json={"actual_pct": actual_pct, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Login Service SLO", service="auth", target_pct=99.5)
    assert d["name"] == "Login Service SLO"
    assert d["status"] == "draft"
    assert d["target_pct"] == 99.5
    assert d["error_budget_pct"] == pytest.approx(0.5, abs=1e-4)

    r = c.get(f"/api/v1/slos/{d['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "auth"
    assert body["latest_actual_pct"] is None
    assert body["is_breaching"] is None


def test_list_and_filter(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="API SLO",   service="api",   time_window="rolling_7d")
    _create(c, name="DB SLO",    service="db",    time_window="rolling_30d")
    _create(c, name="Cache SLO", service="cache", time_window="rolling_30d")

    r = c.get("/api/v1/slos")
    assert r.status_code == 200
    assert r.json()["total"] == 3

    r = c.get("/api/v1/slos?time_window=rolling_7d")
    assert r.json()["total"] == 1

    r = c.get("/api/v1/slos?q=db")
    assert r.json()["total"] == 1


def test_patch(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.patch(f"/api/v1/slos/{d['id']}", json={"target_pct": 99.0, "owner": "platform-team"})
    assert r.status_code == 200
    body = r.json()
    assert body["target_pct"] == 99.0
    assert body["owner"] == "platform-team"
    assert body["error_budget_pct"] == pytest.approx(1.0, abs=1e-4)


def test_delete(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/slos/{d['id']}")
    assert r.status_code == 204
    r = c.get(f"/api/v1/slos/{d['id']}")
    assert r.status_code == 404


def test_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/slos/nonexistent").status_code == 404
    assert c.patch("/api/v1/slos/nonexistent", json={}).status_code == 404
    assert c.delete("/api/v1/slos/nonexistent").status_code == 404


# ── Validation ────────────────────────────────────────────────────────────────

def test_target_pct_validation(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    # target_pct must be > 0 and <= 100
    assert c.post("/api/v1/slos", json={"name": "bad", "target_pct": 0}).status_code == 422
    assert c.post("/api/v1/slos", json={"name": "bad", "target_pct": 101}).status_code == 422
    assert c.post("/api/v1/slos", json={"name": "ok", "target_pct": 100}).status_code == 201


def test_invalid_time_window(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/slos", json={"name": "bad", "time_window": "rolling_1y"})
    assert r.status_code == 400


# ── State machine ─────────────────────────────────────────────────────────────

def test_valid_transitions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    sid = d["id"]

    # draft → active
    r = _transition(c, sid, "active")
    assert r.status_code == 200
    assert r.json()["status"] == "active"

    # active → paused
    r = _transition(c, sid, "paused")
    assert r.status_code == 200

    # paused → active
    r = _transition(c, sid, "active")
    assert r.status_code == 200

    # active → deprecated
    r = _transition(c, sid, "deprecated")
    assert r.status_code == 200


def test_invalid_transition(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    # draft → paused is not allowed
    r = _transition(c, d["id"], "paused")
    assert r.status_code == 400

    # transition to unknown status
    r = _transition(c, d["id"], "deleted")
    assert r.status_code == 400


def test_terminal_states_block_transitions(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    sid = d["id"]

    _transition(c, sid, "cancelled")
    # cancelled is terminal — no further transitions allowed
    r = _transition(c, sid, "active")
    assert r.status_code == 400


# ── Measurements ──────────────────────────────────────────────────────────────

def test_add_and_list_measurements(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, target_pct=99.5)
    sid = d["id"]

    r = _measure(c, sid, 99.8, good_events=998, total_events=1000)
    assert r.status_code == 201
    body = r.json()
    assert body["is_breaching"] is False

    r = _measure(c, sid, 98.0)
    assert r.status_code == 201
    assert r.json()["is_breaching"] is True

    r = c.get(f"/api/v1/slos/{sid}/measurements")
    assert r.status_code == 200
    meas = r.json()
    assert meas["total"] == 2


def test_measurement_reflected_in_slo(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, target_pct=99.9)
    sid = d["id"]

    _measure(c, sid, 98.0)

    r = c.get(f"/api/v1/slos/{sid}")
    body = r.json()
    assert body["latest_actual_pct"] == pytest.approx(98.0)
    assert body["is_breaching"] is True
    # error_budget = 0.1; consumed = (99.9 - 98.0) / 0.1 * 100 = 1900 → capped at 1900
    assert body["error_budget_consumed_pct"] > 100


def test_measurement_not_breaching(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, target_pct=99.0)
    sid = d["id"]

    _measure(c, sid, 99.5)

    r = c.get(f"/api/v1/slos/{sid}")
    body = r.json()
    assert body["is_breaching"] is False
    assert body["error_budget_consumed_pct"] == pytest.approx(0.0)


def test_measurement_actual_pct_validation(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    sid = d["id"]
    assert c.post(f"/api/v1/slos/{sid}/measurements", json={"actual_pct": -1}).status_code == 422
    assert c.post(f"/api/v1/slos/{sid}/measurements", json={"actual_pct": 101}).status_code == 422


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/slos/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["active"] == 0
    assert body["breaching"] == 0


def test_stats_with_data(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="SLO-1", target_pct=99.9)
    d2 = _create(c, name="SLO-2", target_pct=99.5)

    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")

    _measure(c, d1["id"], 98.0)   # breaching
    _measure(c, d2["id"], 99.8)   # healthy

    r = c.get("/api/v1/slos/stats")
    body = r.json()
    assert body["total"] == 2
    assert body["active"] == 2
    assert body["breaching"] == 1
    assert body["avg_target"] is not None
